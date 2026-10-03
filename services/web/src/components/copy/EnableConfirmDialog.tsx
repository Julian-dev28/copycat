import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";

export function EnableConfirmDialog({
  open,
  onCancel,
  onConfirm,
  confirming,
}: {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  confirming?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title="Trade with real money?"
      description="Dry run is off. Turning this on lets the engine place real orders on Hyperliquid on your behalf, mirroring your leaders at the leverage and sizing you've configured."
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={confirming}>
            {confirming ? "Enabling…" : "Enable real trading"}
          </Button>
        </>
      }
    />
  );
}
