"use client";
import { useEffect, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import { gameLabel } from "../lib/payment-games";

export default function PaymentGamePicker({ agency, businessDate, value, onChange, disabled }) {
  const [state, setState] = useState({ key: "", loading: true, games: [], error: "" });
  const [retry, setRetry] = useState(0);
  const requestKey = `${agency}:${businessDate}:${retry}`;
  useEffect(() => {
    let active = true;
    if (!agency || !businessDate) return;
    clientRequest(apiPath(`agencies/${agency}/payment-effective-games/?business_date=${encodeURIComponent(businessDate)}`))
      .then((games) => { if (active) setState({ key: requestKey, loading: false, games, error: "" }); })
      .catch((failure) => {
        if (active) setState({
          key: requestKey,
          loading: false,
          games: [],
          error: failure?.status >= 500
            ? "The effective-games service is temporarily unavailable."
            : failure?.message || "Could not load effective games.",
        });
      });
    return () => { active = false; };
  }, [agency, businessDate, retry, requestKey]);
  if (!agency || !businessDate) return <p>Select an agency and business date to load effective games.</p>;
  const current = state.key === requestKey ? state : { loading: true, games: [], error: "" };
  return <div aria-live="polite">
    {current.loading ? <p role="status">Loading effective games…</p> : null}
    {current.error ? <p role="alert">{current.error} <button type="button" onClick={() => setRetry(retry + 1)}>Retry games</button></p> : null}
    {!current.loading && !current.error && !current.games.length ? <p>No effective games for this date.</p> : null}
    <label>Game<select required disabled={disabled || current.loading || !current.games.length} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">Select a game explicitly</option>
      {current.games.map((game) => <option key={game.game_id} value={game.game_id}>{gameLabel(game)}</option>)}
    </select></label>
    {value ? <p>Review selected game: {gameLabel(current.games.find((game) => String(game.game_id) === String(value)))}</p> : null}
  </div>;
}
