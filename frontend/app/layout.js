import "./globals.css";

export const metadata = {
  title: "Treasureland Investment Limited",
  description: "Secure operations platform for Treasureland Investment Limited.",
  icons: {
    icon: "/brand/treasureland-logo.png",
    apple: "/brand/treasureland-logo.png",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
