import Image from "next/image";

const logo = {
  src: "/brand/treasureland-logo.png",
  alt: "Treasureland Investment Limited logo",
};

export function BrandLogo({ size = "sidebar" }) {
  const imageSize = size === "login" ? 112 : size === "inline" ? 34 : 52;
  return (
    <div className={`brand-logo-panel ${size}`} aria-label={logo.alt}>
      <Image
        src={logo.src}
        alt={logo.alt}
        width={imageSize}
        height={imageSize}
        sizes={`${imageSize}px`}
        priority={size === "login"}
      />
    </div>
  );
}

export default function BrandIdentity({ variant = "sidebar", subtitle = "Secure operations" }) {
  return (
    <div className={`brand-block ${variant}`}>
      <BrandLogo size={variant === "login" ? "login" : variant === "mobile" ? "inline" : "sidebar"} />
      <div>
        <p className="brand-title">Treasureland Investment Limited</p>
        <p className="brand-subtitle">{subtitle}</p>
      </div>
    </div>
  );
}
