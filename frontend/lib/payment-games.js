export const GAME_CATEGORIES = { TIMED: "Timed", GHANA: "Ghana (Whole Day)", DOUBLE_CHANCE: "Double Chance" };
export function gameLabel(game) {
  if (!game) return "Game: Not assigned - legacy obligation.";
  const times = game.is_whole_day ? "Whole Day" : `Closing ${game.closing_time || "?"} / Draw ${game.draw_time || "?"}`;
  return `${game.name} ? ${GAME_CATEGORIES[game.category] || game.category} ? ${game.business_date} ? ${times}${game.holiday_override_applied ? ` ? Holiday Override / Holiday Game: ${game.holiday_name}` : ""}`;
}
