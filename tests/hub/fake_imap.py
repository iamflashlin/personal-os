"""A tiny IMAP4rev1 server on 127.0.0.1, enough to test the email connector.

It speaks plain IMAP (no TLS), knows one user and one folder, can insist on the `ID`
command the way NetEase 163 does, and records every command so tests can prove the
connector never changes anything (no STORE, no EXPUNGE, only BODY.PEEK). It can also
refuse one message, drop the connection at one message, and reject a malformed SINCE date
the way real servers answer BAD.
"""

import re
import socketserver
import threading
from dataclasses import dataclass, field

_SINCE = re.compile(r"SINCE \d{1,2}-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{4}")


@dataclass
class Message:
    uid: int
    raw: bytes
    seen: bool = False
    received: str = "10-Nov-2026 09:30:00 -0800"  # IMAP INTERNALDATE


@dataclass
class Mailbox:
    username: str
    password: str
    uidvalidity: int = 7
    require_id: bool = True  # like NetEase: SELECT/EXAMINE fails until ID was sent
    messages: list[Message] = field(default_factory=list[Message])
    commands: list[str] = field(default_factory=list[str])
    refuse_uid: int | None = None  # FETCH of this message's body answers NO
    drop_at_uid: int | None = None  # the connection closes when this body is fetched

    def add(self, raw: bytes, seen: bool = False, received: str | None = None) -> Message:
        uid = max((m.uid for m in self.messages), default=100) + 1
        message = Message(uid=uid, raw=raw, seen=seen)
        if received:
            message.received = received
        self.messages.append(message)
        return message


def _uids(text: str) -> set[int]:
    wanted: set[int] = set()
    for piece in text.split(","):
        if ":" in piece:
            low, high = piece.split(":", 1)
            wanted.update(range(int(low), int(high) + 1))
        elif piece.isdigit():
            wanted.add(int(piece))
    return wanted


class FakeImapServer:
    def __init__(self, mailbox: Mailbox) -> None:
        box = mailbox

        class Handler(socketserver.StreamRequestHandler):
            def send(self, line: str | bytes) -> None:
                data = line if isinstance(line, bytes) else line.encode()
                self.wfile.write(data + b"\r\n")

            def literal(self, prefix: str, payload: bytes, suffix: str = ")") -> None:
                self.send(f"{prefix}{{{len(payload)}}}".encode())
                self.wfile.write(payload)
                self.send(suffix)

            def handle(self) -> None:
                self.send("* OK fake IMAP ready")
                logged_in = identified = False
                while True:
                    raw = self.rfile.readline()
                    if not raw:
                        return
                    line = raw.decode(errors="replace").rstrip("\r\n")
                    tag, _, rest = line.partition(" ")
                    command, _, args = rest.partition(" ")
                    command = command.upper()
                    if command == "UID":
                        sub, _, args = args.partition(" ")
                        command = f"UID {sub.upper()}"
                    # A LOGIN line holds the password: record only the command.
                    box.commands.append(command if command == "LOGIN" else f"{command} {args}")
                    if command == "CAPABILITY":
                        self.send("* CAPABILITY IMAP4rev1 ID AUTH=PLAIN")
                        self.send(f"{tag} OK done")
                    elif command == "LOGIN":
                        user, password = (a.strip('"') for a in args.split(" ", 1))
                        if user == box.username and password == box.password:
                            logged_in = True
                            self.send(f"{tag} OK logged in")
                        else:
                            self.send(f"{tag} NO [AUTHENTICATIONFAILED] login failed")
                    elif command == "ID":
                        identified = True
                        self.send('* ID ("name" "fake")')
                        self.send(f"{tag} OK id done")
                    elif command in ("SELECT", "EXAMINE"):
                        if not logged_in:
                            self.send(f"{tag} BAD not logged in")
                        elif box.require_id and not identified:
                            self.send(f"{tag} NO Unsafe Login. Please contact kefu@example.com")
                        else:
                            self.send(f"* {len(box.messages)} EXISTS")
                            self.send(f"* OK [UIDVALIDITY {box.uidvalidity}] ok")
                            mode = "READ-ONLY" if command == "EXAMINE" else "READ-WRITE"
                            self.send(f"{tag} OK [{mode}] done")
                    elif command == "UID SEARCH":
                        hits = self.search(args)
                        if hits is None:
                            self.send(f"{tag} BAD invalid search criteria")
                        else:
                            self.send("* SEARCH " + " ".join(str(u) for u in hits))
                            self.send(f"{tag} OK search done")
                    elif command == "UID FETCH":
                        if not self.fetch(tag, args):
                            return  # dropped on purpose
                    elif command == "LOGOUT":
                        self.send("* BYE bye")
                        self.send(f"{tag} OK logout")
                        return
                    elif command == "NOOP":
                        self.send(f"{tag} OK noop")
                    else:
                        self.send(f"{tag} BAD unknown command")

            def fetch(self, tag: str, args: str) -> bool:
                uid_text, _, items = args.partition(" ")
                wanted = _uids(uid_text)
                for seq, m in enumerate(box.messages, start=1):
                    if m.uid not in wanted:
                        continue
                    flags = "(\\Seen)" if m.seen else "()"
                    if "BODY.PEEK" in items:
                        if m.uid == box.drop_at_uid:
                            self.wfile.flush()
                            self.connection.close()
                            return False
                        if m.uid == box.refuse_uid:
                            self.send(f"{tag} NO message is temporarily unavailable")
                            return True
                    if "BODY.PEEK[HEADER]" in items:
                        head, _, body = m.raw.partition(b"\r\n\r\n")
                        size = int(re.search(r"<0\.(\d+)>", items).group(1))  # type: ignore[union-attr]
                        opening = f"* {seq} FETCH (UID {m.uid} BODY[HEADER] {{{len(head) + 4}}}"
                        self.send(opening)
                        self.wfile.write(head + b"\r\n\r\n")
                        self.literal(" BODY[TEXT]<0> ", body[:size])
                    elif "BODY.PEEK[]" in items:
                        self.literal(f"* {seq} FETCH (UID {m.uid} BODY[] ", m.raw)
                    else:
                        meta = f"UID {m.uid} FLAGS {flags}"
                        if "RFC822.SIZE" in items:
                            meta += f" RFC822.SIZE {len(m.raw)}"
                        if "INTERNALDATE" in items:
                            meta += f' INTERNALDATE "{m.received}"'
                        self.send(f"* {seq} FETCH ({meta})")
                self.send(f"{tag} OK fetch done")
                return True

            def search(self, args: str) -> list[int] | None:
                uids = [m.uid for m in box.messages]
                ranged = re.fullmatch(r"UID (\d+):\*", args.strip())
                if ranged:
                    low = int(ranged.group(1))
                    # IMAP: "n:*" always includes the highest UID, even if it is below n.
                    return sorted({u for u in uids if u >= low} | ({max(uids)} if uids else set()))
                if _SINCE.fullmatch(args.strip()):
                    return uids  # every message here counts as recent
                return None

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
