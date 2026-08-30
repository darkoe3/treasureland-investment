import { redirect } from "next/navigation";

export default async function NewDailySheetPage() {
  redirect("/dashboard/daily-sheets");
}
