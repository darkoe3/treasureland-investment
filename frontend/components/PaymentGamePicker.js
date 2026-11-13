"use client";
import { useEffect, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import { gameLabel } from "../lib/payment-games";

export default function PaymentGamePicker({ agency, businessDate, value, onChange, disabled }) {
  const [state, setState] = useState({ loading: true, games: [], error: "" });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    if (!agency || !businessDate) return;
    clientRequest(apiPath(`agencies/${agency}/payment-effective-games/?business_date=${encodeURIComponent(businessDate)}`))
      .then((games) => { if (active) setState({ loading: false, games, error: "" }); })
      .catch(() => { if (active) setState({ loading: false, games: [], error: "Could not load effective games. Retry before creating an obligation." }); });
    return () => { active = false; };
  }, [agency, businessDate, retry]);
  if (!agency || !businessDate) return <p>Select an agency and business date to load effective games.</p>;
  return <div aria-live="polite">
    {state.loading ? <p role="status">Loading effective games?</p> : null}
    {state.error ? <p role="alert">{state.error} <button type="button" onClick={() => setRetry(retry + 1)}>Retry games</button></p> : null}
    {!state.loading && !state.error && !state.games.length ? <p>No effective games for this date.</p> : null}
    <label>Game<select required disabled={disabled || state.loading || !state.games.length} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">Select a game explicitly</option>
      {state.games.map((game) => <option key={game.game_id} value={game.game_id}>{gameLabel(game)}</option>)}
    </select></label>
    {value ? <p>Review selected game: {gameLabel(state.games.find((game) => String(game.game_id) === String(value)))}</p> : null}
  </div>;
}
