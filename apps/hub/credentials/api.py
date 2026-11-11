from fastapi import APIRouter, Path, Request

from apps.hub.core.http import ActorDep, SessionDep, call
from apps.hub.credentials import service
from packages.contracts.credentials import CREDENTIAL_NAME_PATTERN, Credential, CredentialPut

NameParam = Path(pattern=CREDENTIAL_NAME_PATTERN)


def _store(request: Request) -> service.SecretStore:
    return request.app.state.secret_store


def build_router() -> APIRouter:
    """Set, list and delete. There is deliberately no route that returns a secret."""
    router = APIRouter(prefix="/credentials", tags=["credentials"])

    @router.get("", name="list_credentials")
    def list_all(session: SessionDep, actor: ActorDep) -> list[Credential]:
        return service.list_all(session, actor)

    @router.put("/{name}", name="put_credential")
    def put(
        payload: CredentialPut,
        request: Request,
        session: SessionDep,
        actor: ActorDep,
        name: str = NameParam,
    ) -> Credential:
        secret = payload.secret.get_secret_value()
        return call(
            lambda: service.put(session, actor, _store(request), name, secret, payload.note)
        )

    @router.delete("/{name}", status_code=204, name="delete_credential")
    def delete(
        request: Request, session: SessionDep, actor: ActorDep, name: str = NameParam
    ) -> None:
        call(lambda: service.delete(session, actor, _store(request), name))

    return router
