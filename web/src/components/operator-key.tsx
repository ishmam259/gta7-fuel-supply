"use client";
import { useState } from "react";
import { KeyRound, LockOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { setOperatorKey } from "@/lib/api";
import { useOperatorKey } from "@/lib/hooks";

/** Sensitive actions (approve/reject, mode, sim control, chaos) need X-Operator-Key (brief §18). Kept in sessionStorage. */
export function OperatorKeyButton() {
  const key = useOperatorKey();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  return (
    <>
      <Button
        variant={key ? "secondary" : "outline"}
        size="sm"
        onClick={() => {
          setDraft("");
          setOpen(true);
        }}
      >
        {key ? <LockOpen /> : <KeyRound />}
        {key ? "Operator" : "Operator key"}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Operator key</DialogTitle>
            <DialogDescription>
              Approving allocations, changing the decision mode and chaos controls are restricted. The key is kept only in this browser tab
              (sessionStorage) and sent as the <code>X-Operator-Key</code> header.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOperatorKey(draft.trim());
              setOpen(false);
            }}
            className="space-y-3"
          >
            <Input type="password" autoFocus placeholder={key ? "•••••• (set) — enter a new key to replace" : "OPERATOR_KEY"} value={draft} onChange={(e) => setDraft(e.target.value)} />
            <DialogFooter>
              {key && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setOperatorKey("");
                    setOpen(false);
                  }}
                >
                  Sign out
                </Button>
              )}
              <Button type="submit" disabled={!draft.trim()}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
