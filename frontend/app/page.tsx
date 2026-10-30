import PortalShell from "./PortalShell";
import StaffDashboard from "./StaffDashboard";
import PatientPortal from "./PatientPortal";

export const dynamic = "force-dynamic";

export default function Page() {
  const audience = process.env.WARD_PORTAL === "patient" ? "patient" : "staff";
  return <PortalShell audience={audience}>{audience === "patient" ? <PatientPortal /> : <StaffDashboard />}</PortalShell>;
}
