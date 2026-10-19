import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, meOptions, panelMatchOptions, refreshPlantWorkbooks } from "@/api/queries";
import { mayCorrect, mayIngest } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import {
  acceptAllYellow,
  attentionLabel,
  blockedFor,
  bulkAcceptSummary,
  canConfirm,
  carryOverLabel,
  choosableFor,
  confirmBlocker,
  confirmedPairs,
  type Decisions,
  effectiveDecisions,
  filteredOut,
  isExhaustion,
  mappablePanels,
  panelKey,
  panelMatchProposal,
  ruleDisagreement,
  scoreLabel,
  signalLabel,
  suggestionFor,
  walkMatch,
  walkOf,
} from "./panel-match";

type PanelMatch = components["schemas"]["PanelMatchOut"];
type HeldPanel = components["schemas"]["HeldPanelOut"];

const UNMATCHED = "__unmatched__";
const selectClass =
  "mt-1 min-h-11 w-full rounded-[var(--radius-sm)] border border-border bg-[var(--surface-2)] px-3 text-xs";
const inputClass =
  "mt-1 min-h-11 w-full rounded-[var(--radius-sm)] border border-border bg-[var(--surface-2)] px-3 text-xs";

/**
 * T86: match this file's panel names to the plant's own panels.
 *
 * The person answers; this screen only sorts. Each held name is shown with
 * the number the file wrote beside it and the server's name-scored
 * suggestions underneath. A panel reaches the list on its NAME alone --
 * `14ROOF` and `14LFBOXSD` share a number and nothing else, which is why
 * T86 exists -- and T87 then lets the number put the panel carrying it
 * first, saying so in that suggestion's own basis (D-87-1 / D-87-2).
 * Confirm stays disabled until every name is either matched or explicitly
 * left unmatched.
 *
 * Nothing here applies. The Engineer proposes the whole set, an Admin
 * approves it, and the sheet is read again (D-86-4).
 */
export function PanelMatchDialog({
  loadId,
  modelCode,
  plant,
  fileHash,
  onClose,
}: {
  loadId: number;
  modelCode: string;
  plant: string;
  fileHash?: string;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const identity = useQuery(meOptions);
  const ingest =
    !identity.isError &&
    mayIngest(identity.data?.principal) &&
    mayCorrect(identity.data?.principal);
  const [decisions, setDecisions] = useState<Decisions>({});
  // T88 (D-88-2): confirming a pair re-solves the rest around it. The pairs
  // already decided are pinned server-side (G-88-4), so a re-solve can only
  // fill what is still open.
  const view = useQuery(panelMatchOptions(loadId, modelCode, confirmedPairs(decisions)));
  const [retire, setRetire] = useState<string[]>([]);
  const [retireReason, setRetireReason] = useState("");
  const [decidedBy, setDecidedBy] = useState("");
  const [method, setMethod] = useState("");
  const [note, setNote] = useState("");
  const [localError, setLocalError] = useState<Error | null>(null);
  const [proposedId, setProposedId] = useState<string | null>(null);

  const propose = useMutation({
    // The body is built and validated in the click handler, so a refusal the
    // screen can answer by itself ("two names onto one panel") is shown as
    // the sentence it is instead of arriving as a failed request.
    mutationFn: (body: components["schemas"]["ProposalCreate"]) => api().propose(body),
    retry: false,
    onSuccess: async (result) => {
      setProposedId(result.id);
      setLocalError(null);
      await client.invalidateQueries({ queryKey: ["proposals", loadId] });
      await client.invalidateQueries({ queryKey: ["batch", loadId] });
      await refreshPlantWorkbooks(client, plant);
      if (fileHash) await client.invalidateQueries({ queryKey: ["worksheet", plant, fileHash] });
    },
  });

  const body = () => {
    if (identity.isPending || view.isPending)
      return <LoadingState>Loading this model&apos;s panel list...</LoadingState>;
    if (view.isError) return <ApiErrorState error={view.error} retry={() => void view.refetch()} />;
    const data: PanelMatch = view.data;
    // Still read for the retirement list and the count line: those are
    // about the whole catalogue, not about answering one name.
    const choosable = mappablePanels(data);
    const blocker = confirmBlocker(data, decisions);
    // T89 (D-89-9): what the person has said, over what was carried over.
    const answers = effectiveDecisions(data, decisions);
    const ready = ingest && canConfirm(data, decisions);
    return (
      <div className="space-y-5">
        <p className="text-sm">{data.operator_message}</p>
        {/* G-88-2: said BEFORE any exhaustion claim, naming both numbers. */}
        {data.catalogue_warning && (
          <p role="alert" className="border border-border p-3 text-xs font-medium">
            {data.catalogue_warning}
          </p>
        )}
        {(data.orientation_conflicts ?? []).length > 0 && (
          <p role="alert" className="border border-border p-3 text-xs font-medium">
            The file writes more than one Tolerance Group for{" "}
            {(data.orientation_conflicts ?? []).join(", ")}. A panel is Horizontal or Vertical, not
            both &mdash; check the spreadsheet. Those names get no orientation filter and no
            &quot;only one left&quot; suggestion.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {data.plant_code} / {data.model_code} &middot; {data.held_panels.length} panel name
          {data.held_panels.length === 1 ? "" : "s"} held &middot; {choosable.length} panel
          {choosable.length === 1 ? "" : "s"} you can match onto
        </p>

        <WalkSummary
          view={data}
          disabled={!ingest || propose.isPending || !!proposedId}
          onAcceptYellow={() =>
            setDecisions((current) => ({ ...acceptAllYellow(data), ...current }))
          }
        />

        <ol aria-label="Held panel names" className="space-y-3">
          {data.held_panels.map((held) => (
            <PanelRow
              key={panelKey(held)}
              held={held}
              loadId={loadId}
              decision={answers[panelKey(held)]}
              disabled={!ingest || propose.isPending || !!proposedId}
              onDecide={(decision) =>
                setDecisions((current) => ({ ...current, [panelKey(held)]: decision }))
              }
            />
          ))}
        </ol>

        <section
          className="space-y-2 border border-border p-3"
          aria-label="Which panels does this replace"
        >
          <h4 className="text-sm font-semibold">Which panels does this replace?</h4>
          <p className="text-xs">
            Only you can say which block of panels this file&apos;s names replace. Retiring keeps
            every old reading readable and stops new uploads matching onto those panels. A panel you
            matched onto above cannot also be retired. Leave this empty if nothing is replaced.
          </p>
          <label className="block text-xs" htmlFor={`panel-retire-${loadId}`}>
            Panels this set supersedes
            <select
              id={`panel-retire-${loadId}`}
              multiple
              size={6}
              className={`${selectClass} min-h-32`}
              value={retire}
              disabled={!ingest || propose.isPending || !!proposedId}
              onChange={(event) =>
                setRetire(Array.from(event.target.selectedOptions, (option) => option.value))
              }
            >
              {data.live_panels.map((panel) => (
                <option key={panel.zone_code} value={panel.zone_code}>
                  {panel.point_no}. {panel.zone_code}
                  {panel.note ? ` -- ${panel.note}` : ""}
                </option>
              ))}
            </select>
          </label>
          {retire.length > 0 && (
            <label className="block text-xs" htmlFor={`panel-retire-reason-${loadId}`}>
              Why are they superseded? (stored on every retired panel)
              <input
                id={`panel-retire-reason-${loadId}`}
                className={inputClass}
                value={retireReason}
                disabled={propose.isPending || !!proposedId}
                onChange={(event) => setRetireReason(event.target.value)}
              />
            </label>
          )}
        </section>

        <section
          className="space-y-2 border border-border p-3"
          aria-label="Who decided this panel set"
        >
          <h4 className="text-sm font-semibold">Who decided this, and how?</h4>
          <p className="text-xs">
            We record the person who said which panel each name is -- not whoever is signed in,
            because you may be passing on the plant&apos;s answer.
          </p>
          <label className="block text-xs" htmlFor={`panel-decided-${loadId}`}>
            Who decided
            <input
              id={`panel-decided-${loadId}`}
              className={inputClass}
              value={decidedBy}
              disabled={propose.isPending || !!proposedId}
              onChange={(event) => setDecidedBy(event.target.value)}
            />
          </label>
          <label className="block text-xs" htmlFor={`panel-method-${loadId}`}>
            How they decided
            <input
              id={`panel-method-${loadId}`}
              className={inputClass}
              value={method}
              disabled={propose.isPending || !!proposedId}
              onChange={(event) => setMethod(event.target.value)}
            />
          </label>
          <label className="block text-xs" htmlFor={`panel-note-${loadId}`}>
            Note
            <input
              id={`panel-note-${loadId}`}
              className={inputClass}
              value={note}
              disabled={propose.isPending || !!proposedId}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
        </section>

        {!ingest && <p className="text-sm">Sign in as an Engineer to match these panels.</p>}
        {blocker && !proposedId && (
          <p role="status" className="text-sm">
            {blocker}
          </p>
        )}
        {proposedId && (
          <p role="status" className="text-sm">
            Panel set proposed. An Admin approves it under this sheet&apos;s mapping proposals; the
            sheet is then read again and nothing loads until they do.
          </p>
        )}
        {localError && (
          <p role="alert" className="text-sm font-medium">
            {localError.message}
          </p>
        )}
        {propose.isError && <ApiErrorState error={propose.error} />}
        <div className="flex flex-wrap gap-2">
          <Button
            className="min-h-11"
            disabled={!ready || propose.isPending || !!proposedId}
            onClick={() => {
              try {
                setLocalError(null);
                propose.mutate(
                  panelMatchProposal({
                    view: data,
                    decisions,
                    retireZoneCodes: retire,
                    retireReason,
                    decidedBy,
                    method,
                    note,
                  }),
                );
              } catch (error) {
                setLocalError(error instanceof Error ? error : new Error(String(error)));
              }
            }}
          >
            Confirm this panel set
          </Button>
          <Button variant="outline" className="min-h-11" onClick={onClose}>
            {proposedId ? "Close" : "Cancel"}
          </Button>
        </div>
      </div>
    );
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogTitle>Match the panel list</DialogTitle>
        <DialogDescription>
          Match each panel name in this file to the panel it is on {plant}&apos;s {modelCode} list.
          Suggestions are narrowed by the orientation the file wrote, then ranked by name and by the
          walk number, and each one says which of those argued for it. Where the constraints leave
          exactly one panel open, it says so in those words. Nothing is applied until you confirm
          the whole set.
        </DialogDescription>
        {body()}
      </DialogContent>
    </Dialog>
  );
}

/**
 * T90: the whole-set view, which stays (D-90-9), and the one click (D-90-5).
 *
 * The walk is the identity and the name is only a label, so this says what
 * the file's *structure* is -- the group fingerprint, whether it is the
 * canonical one, which rule applies and why -- before any individual name is
 * argued about. 32-at-once is how the owner checks the pattern.
 *
 * The button accepts the **yellow** rows only and reports both numbers
 * (D-90-14). A red is never swept along, and even a walk confirmed last
 * month needs this one click: there is no silence (D-90-5).
 */
function WalkSummary({
  view,
  disabled,
  onAcceptYellow,
}: {
  view: PanelMatch;
  disabled: boolean;
  onAcceptYellow: () => void;
}) {
  const walk = walkMatch(view);
  if (!walk) return null;
  const bulk = bulkAcceptSummary(view);
  return (
    <section
      className="space-y-2 border border-border p-3 text-xs"
      aria-label="The walk this file describes"
      data-fingerprint={walk.fingerprint}
    >
      <h4 className="text-sm font-semibold">The walk this file describes</h4>
      <p role="status">{walk.operator_message}</p>
      <dl className="grid gap-1 sm:grid-cols-[10rem_1fr]">
        <dt className="text-muted-foreground">This file</dt>
        <dd className="font-mono break-words">{walk.fingerprint_display}</dd>
        <dt className="text-muted-foreground">{view.model_code}&apos;s own walk</dt>
        <dd className="font-mono break-words">{walk.canonical_fingerprint_display}</dd>
      </dl>
      <p className="text-muted-foreground">
        {walk.multiset_matches
          ? "The file walks the same panel families, as many of each, as this model's own list."
          : "The file does not walk the same families as this model's own list: " +
            walk.group_counts
              .filter((count) => count.file !== count.canonical)
              .map((count) => `${count.panel_group} ${count.file} against ${count.canonical}`)
              .join(", ") +
            "."}
      </p>
      <p className="text-muted-foreground" data-walk-order={String(walk.walk_order_verified)}>
        Walk order: {walk.walk_order_reason}.
      </p>
      <ul className="space-y-1">
        <li data-rule="group_ordinal">
          <strong>By family and position:</strong>{" "}
          {walk.rule_group_ordinal_available ? "applies" : "does not apply"} &mdash;{" "}
          {walk.rule_group_ordinal_reason}
        </li>
        <li data-rule="walk_number">
          <strong>By the file&apos;s own number:</strong>{" "}
          {walk.rule_walk_number_available ? "applies" : "does not apply"} &mdash;{" "}
          {walk.rule_walk_number_reason}
        </li>
      </ul>
      {(walk.disagreements ?? []).length > 0 && (
        <p role="alert" className="font-medium">
          The two rules disagree about {(walk.disagreements ?? []).join(", ")}. Neither answer is
          proposed for those names, and nothing else in this set is taken on trust either &mdash; a
          disagreement is information about the whole alignment.
        </p>
      )}
      <p>
        {walk.yellow_count} look right, {walk.red_count} need attention. There is no &quot;confirmed
        by itself&quot;: you confirm the set.
      </p>
      {bulk && (
        <Button variant="outline" className="min-h-11" disabled={disabled} onClick={onAcceptYellow}>
          {bulk.words}
        </Button>
      )}
    </section>
  );
}

function PanelRow({
  held,
  loadId,
  decision,
  disabled,
  onDecide,
}: {
  held: HeldPanel;
  loadId: number;
  decision: Decisions[string] | undefined;
  disabled: boolean;
  onDecide: (decision: Decisions[string]) => void;
}) {
  const suggestion = suggestionFor(held);
  // T89 (D-89-6): the one list, from the server, in the server's order.
  const choices = choosableFor(held);
  const blocked = blockedFor(held);
  const carried = carryOverLabel(held);
  const selectId = `panel-match-${loadId}-${held.raw_zone_text}`;
  const value = decision ? (decision.kind === "unmatched" ? UNMATCHED : decision.zoneCode) : "";
  // T90 (D-90-9): the control is IN the row. The whole-set view stays above.
  const walk = walkOf(held);
  const disagreement = walk ? ruleDisagreement(walk) : null;
  const answer = walk?.prefilled_zone_code ?? walk?.proposed_zone_code ?? null;
  return (
    <li
      className="space-y-2 border border-border p-3 text-xs"
      data-raw={held.raw_zone_text}
      data-attention={walk?.attention}
      data-specificity={walk?.specificity}
      data-binding={walk?.binding}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-semibold">
          {held.raw_zone_text}
          {walk && (
            <span className="ml-2 font-normal" data-walk-attention={walk.attention}>
              &mdash; {attentionLabel(walk)}
            </span>
          )}
        </p>
        <p className="text-muted-foreground">
          {held.raw_position === null || held.raw_position === undefined
            ? "No number in this name"
            : `Number ${held.raw_position} in the file - only orders the suggestions, never adds one`}{" "}
          &middot; {held.count} reading{held.count === 1 ? "" : "s"} held
        </p>
      </div>
      {/* T88 (D-88-3): every proposal says which signal argued for it, in
          words. Exhaustion is the one that can be confidently wrong, so it
          is labelled loudest and carries the counts it rests on. */}
      {held.proposed_zone_code ? (
        <p className="text-muted-foreground" data-signal={held.signal}>
          <strong>{signalLabel(held)}</strong>
          {isExhaustion(held) ? " \u2014 check this one especially: " : ": "}
          <strong>{held.proposed_zone_code}</strong>
          {suggestion && suggestion.zone_code === held.proposed_zone_code
            ? ` (${scoreLabel(suggestion)})`
            : ""}
          . {held.signal_reason}. Check it yourself before you confirm.
        </p>
      ) : (
        <p className="text-muted-foreground" data-signal={held.signal}>
          {held.signal_reason || "No panel on this list has a close enough name."} Pick one from the
          full list if you know which it is, or leave it unmatched.
        </p>
      )}
      {held.orientation_conflict && (
        <p className="text-muted-foreground">
          This name is written with more than one Tolerance Group in the file, so orientation was
          not used to narrow it down.
        </p>
      )}
      {filteredOut(held).length > 0 && (
        <p className="text-muted-foreground">
          {filteredOut(held).length} panel(s) of the other orientation are not suggested but are
          still in the list below.
        </p>
      )}
      {/* T90: the structural reading of this row, inline (D-90-9): what the
          walk says this panel is, why, and -- when the two rules disagree --
          both answers with neither proposed (D-90-2). */}
      {walk && (
        <div className="space-y-1 border-l-2 border-border pl-2" data-walk-row>
          <p>
            <strong>{attentionLabel(walk)}</strong>
            {walk.proposed_zone_code ? (
              <>
                : the walk says this is <strong>{walk.proposed_zone_code}</strong>.
              </>
            ) : (
              ": the walk proposes nothing here."
            )}{" "}
            {walk.reason}.
          </p>
          {disagreement && (
            <p role="alert">
              By family and position it is <strong>{disagreement.groupOrdinal}</strong>; by the
              file&apos;s own number it is <strong>{disagreement.walkNumber}</strong>. Both are
              shown and neither is filled in &mdash; you choose.
            </p>
          )}
          {!walk.side_hint_checked && walk.proposed_zone_code && (
            <p className="text-muted-foreground">
              Nothing here carries a left or right, so there was no side to cross-check.
            </p>
          )}
          {walk.specificity === "rough" && walk.binding !== "batch" && (
            <p className="text-muted-foreground">
              This name shares its wording with others in this file, so its number is what
              identifies it. Confirming it applies to <strong>this upload</strong>; it is not
              learned forever, because the walk can be reshuffled.
            </p>
          )}
          {/* T91 (D-91-2, D-91-3): the row says how far confirming it
              travels, and when the plant itself has called this spelling a
              different panel it says which file did, because that is the
              case `specificity` on its own cannot see. */}
          {walk.binding === "batch" && (
            <p className="text-muted-foreground" data-binding="batch">
              Confirming this applies to <strong>this upload only</strong>, and it is recorded on it
              &mdash; never learned forever.{" "}
              {walk.binding_reason
                ? `${walk.binding_reason[0].toUpperCase()}${walk.binding_reason.slice(1)}.`
                : "This name does not identify a panel on its own here."}
            </p>
          )}
          {answer && !decision && (
            <Button
              variant="outline"
              className="min-h-11"
              disabled={disabled}
              onClick={() => onDecide({ kind: "match", zoneCode: answer })}
            >
              It is {answer}
            </Button>
          )}
        </div>
      )}
      {/* T89 (D-89-9): pre-selected, and said out loud. Still confirmed by a
          person -- the selection is a starting point, not an answer. */}
      {carried && (
        <p role="status" data-carried={held.carried_over?.kind}>
          {carried} It is filled in below; check it and confirm, or change it.
        </p>
      )}
      <label className="block" htmlFor={selectId}>
        Which panel is &quot;{held.raw_zone_text}&quot;?
        <select
          id={selectId}
          className={selectClass}
          value={value}
          disabled={disabled}
          onChange={(event) => {
            const next = event.target.value;
            if (!next) return;
            onDecide(
              next === UNMATCHED ? { kind: "unmatched" } : { kind: "match", zoneCode: next },
            );
          }}
        >
          <option value="">Choose a panel</option>
          {choices.map((code) => {
            const scored = (held.candidates ?? []).find((c) => c.zone_code === code);
            return (
              <option key={`choose-${code}`} value={code}>
                {scored ? `${code} - ${scoreLabel(scored)} (number ${scored.point_no})` : code}
              </option>
            );
          })}
          {/* D-89-6: taken panels last, disabled, named. */}
          {blocked.map((panel) => (
            <option key={`taken-${panel.zone_code}`} value={panel.zone_code} disabled>
              {panel.zone_code} - {panel.label}
            </option>
          ))}
          <option value={UNMATCHED}>Leave this name unmatched</option>
        </select>
      </label>
      {decision?.kind === "unmatched" && (
        <p role="status">
          Left unmatched. These {held.count} reading{held.count === 1 ? "" : "s"} stay held.
        </p>
      )}
    </li>
  );
}
