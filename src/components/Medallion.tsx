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
        // lazy: with hundreds of people, eager medallions monopolize the
        // WebView's ~6 connections and starve photo-grid thumbnails (#150).
        <img src={src} alt={alt} loading="lazy" decoding="async" />
      ) : (
        <span className="medallion__placeholder" aria-hidden="true" />
      )}
    </div>
  );
}
