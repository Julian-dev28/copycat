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
      description="This turns on live trading: trading enabled with dry run off. The engine will place real orders on Hyperliquid on your behalf, mirroring the traders you copy at the leverage and sizing you've configured."
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
