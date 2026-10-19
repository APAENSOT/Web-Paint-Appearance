import { useState, type Dispatch } from "react";
import {
  monthLabel,
  type Board,
  type BoardAction,
  type BoardItem,
  type ModelLane,
} from "./comparison-board";
export function ItemControls({
  item,
  lane,
  board,
  dispatch,
}: {
  item: BoardItem;
  lane: ModelLane;
  board: Board;
  dispatch: Dispatch<BoardAction>;
}) {
  const [target, setTarget] = useState("");
  const index = lane.items.indexOf(item);
  return (
    <article
      className={`studio-board-item ${item.kind}`}
      aria-label={`${lane.model} ${item.name} board item`}
    >
      <div className="studio-tile-heading">
        <strong>{item.kind === "group" ? item.name : monthLabel(item.months[0])}</strong>
        <details className="studio-actions">
          <summary aria-label={`Actions for ${item.name}`}>Actions</summary>
          <div className="studio-action-menu">
            {item.kind === "group" ? (
              <label>
                Temporary group name
                <input
                  aria-label={`Rename ${item.name}`}
                  className="cv-input"
                  value={item.name}
                  onChange={(e) =>
                    dispatch({ type: "rename", lane: lane.id, id: item.id, name: e.target.value })
                  }
                />
              </label>
            ) : (
              <strong>{monthLabel(item.months[0])}</strong>
            )}
            <div className="studio-toolbar">
              <button
                className="cv-button"
                disabled={index === 0}
                onClick={() =>
                  dispatch({ type: "reorder", lane: lane.id, id: item.id, direction: -1 })
                }
                aria-label={`Move ${item.name} left`}
              >
                Left
              </button>
              <button
                className="cv-button"
                disabled={index === lane.items.length - 1}
                onClick={() =>
                  dispatch({ type: "reorder", lane: lane.id, id: item.id, direction: 1 })
                }
                aria-label={`Move ${item.name} right`}
              >
                Right
              </button>
              <button
                className="cv-button"
                onClick={() => dispatch({ type: "remove", lane: lane.id, id: item.id })}
              >
                Remove {item.name}
              </button>
              {item.kind === "group" && (
                <button
                  className="cv-button"
                  onClick={() => dispatch({ type: "dissolve", lane: lane.id, id: item.id })}
                >
                  Dissolve {item.name}
                </button>
              )}
            </div>
            <label>
              Move destination
              <select
                className="cv-input"
                aria-label={`Move destination for ${item.name}`}
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="">Individual month in {lane.model}</option>
                {board.lanes
                  .filter((l) => l.domain === lane.domain)
                  .flatMap((l) =>
                    l.items
                      .filter((i) => i.kind === "group" && i.id !== item.id)
                      .map((i) => (
                        <option key={i.id} value={`${l.id}|${i.id}`}>
                          {l.model} / {i.name}
                        </option>
                      )),
                  )}
              </select>
            </label>
            {item.months.map((month, n) => (
              <div key={month} className="studio-member">
                <span>{monthLabel(month)}</span>
                {item.kind === "group" && (
                  <>
                    <button
                      className="cv-button"
                      disabled={n === 0}
                      aria-label={`Earlier ${month} in ${item.name}`}
                      onClick={() =>
                        dispatch({
                          type: "member-order",
                          lane: lane.id,
                          id: item.id,
                          month,
                          direction: -1,
                        })
                      }
                    >
                      Earlier
                    </button>
                    <button
                      className="cv-button"
                      disabled={n === item.months.length - 1}
                      aria-label={`Later ${month} in ${item.name}`}
                      onClick={() =>
                        dispatch({
                          type: "member-order",
                          lane: lane.id,
                          id: item.id,
                          month,
                          direction: 1,
                        })
                      }
                    >
                      Later
                    </button>
                  </>
                )}
                <button
                  className="cv-button"
                  aria-label={`Move ${month} from ${item.name}`}
                  onClick={() => {
                    const [targetLane, destination] = target.split("|");
                    dispatch({
                      type: "move",
                      lane: lane.id,
                      id: item.id,
                      month,
                      targetLane: targetLane || lane.id,
                      target: destination || "",
                    });
                  }}
                >
                  Move
                </button>
              </div>
            ))}
          </div>
        </details>
      </div>
      {item.kind === "group" && (
        <div className="studio-connected-months">
          {item.months.map((month) => (
            <span key={month}>{monthLabel(month)}</span>
          ))}
        </div>
      )}
      {!item.months.length && <p className="cv-muted">Add months from the shelf.</p>}
    </article>
  );
}
