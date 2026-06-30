import "./Medallion.css";

interface MedallionProps {
  src: string;
  alt: string;
  selected?: boolean;
  size?: number;
}

export function Medallion({ src, alt, selected = false, size = 48 }: MedallionProps) {
  return (
    <div
      className={`medallion${selected ? " medallion--selected" : ""}`}
      style={{ width: size, height: size }}
      aria-label={alt}
    >
      {src ? (
        <img src={src} alt={alt} />
      ) : (
        <span className="medallion__placeholder" aria-hidden="true" />
      )}
    </div>
  );
}
