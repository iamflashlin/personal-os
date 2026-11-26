import { useRef } from "react";
import { CHANGELOG, CURRENT } from "./releases";
import logo from "./logo.svg";

// The sidebar brand. Hover (or keyboard focus) shows what the newest version changed;
// a click opens every version in a dialog (native <dialog>: Esc and focus come free).
export function Brand() {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = () => dialog.current?.close();

  return (
    <div className="brand-wrap">
      <button
        type="button"
        className="brand"
        aria-label={`Personal OS v${CURRENT.version}，查看版本记录`}
        onClick={() => dialog.current?.showModal()}
      >
        <img className="brand-mark" src={logo} alt="" />
        <span className="brand-name">Personal OS</span>
      </button>
      <div className="brand-pop" role="tooltip">
        <div className="release-head">
          <span className="release-version">v{CURRENT.version}</span>
          <span className="release-date">{CURRENT.date}</span>
        </div>
        <ul className="release-items">
          {CURRENT.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <div className="brand-pop-more">点击看全部版本记录</div>
      </div>
      <dialog
        ref={dialog}
        className="changelog"
        aria-labelledby="changelog-title"
        onClick={(e) => {
          if (e.target === e.currentTarget) close(); // click on the backdrop
        }}
      >
        <div className="changelog-body">
          <div className="changelog-head">
            <h2 id="changelog-title">版本记录</h2>
            <button type="button" className="changelog-close" aria-label="关闭" onClick={close}>
              ×
            </button>
          </div>
          <ol className="changelog-list">
            {CHANGELOG.map((r) => (
              <li key={r.version} className={r === CURRENT ? "release current" : "release"}>
                <div className="release-head">
                  <span className="release-version">v{r.version}</span>
                  <span className="release-date">{r.date}</span>
                  {r === CURRENT && <span className="release-tag">当前</span>}
                </div>
                <ul className="release-items">
                  {r.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </div>
      </dialog>
    </div>
  );
}
