import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  const staff = process.env.WARD_PORTAL !== "patient";
  return {
    id: staff ? "/staff" : "/patient", name: staff ? "Smart Ward · ทีมดูแล" : "Smart Ward · ผู้ป่วย",
    short_name: "Smart Ward", description: "ระบบสาธิตเฝ้าระวังผู้ป่วย ไม่ใช่ระบบฉุกเฉิน",
    start_url: "/", scope: "/", display: "standalone", lang: "th",
    background_color: "#f5f7f4", theme_color: "#176e53",
    icons: [192, 512].map((size) => ({ src: `/smart-ward-${size}.png`, sizes: `${size}x${size}`, type: "image/png", purpose: "any" })),
  };
}
