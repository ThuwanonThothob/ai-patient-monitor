import Image from "next/image";

export default function Brand({ large = false }: { large?: boolean }) {
  return <span className={`ward-brand${large ? " ward-brand-large" : ""}`}>
    <Image src="/smart-ward-mark.svg" alt="" width={large ? 64 : 36} height={large ? 64 : 36} unoptimized />
    <span className="ward-brand-type">
      <span>Smart Ward<span className="ward-brand-ai">AI</span></span>
      {large && <span className="ward-brand-tagline">ดูแลใกล้ชิด แม้อยู่ที่บ้าน · Clinical Telemetry & Decision Support</span>}
    </span>
  </span>;
}
