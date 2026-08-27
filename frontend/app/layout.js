import "./globals.css";

export const metadata = {
  title: "Treasureland Investment Management System",
  description: "Investment management operations platform.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
