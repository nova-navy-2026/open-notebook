'use client'

import { useState } from 'react'
import { NotebookResponse } from '@/lib/types/api'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Link2, Copy, Check, Trash2, Mail, UserMinus } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useToast } from '@/lib/hooks/use-toast'
import {
  useNotebookMembers,
  useNotebookInvites,
  useCreateInvite,
  useRevokeInvite,
  useRemoveMember,
} from '@/lib/hooks/use-collaboration'

interface ShareNotebookDialogProps {
  notebook: NotebookResponse
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ShareNotebookDialog({
  notebook,
  open,
  onOpenChange,
}: ShareNotebookDialogProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const isOwner = notebook.is_owner !== false

  const [email, setEmail] = useState('')
  const [linkUrl, setLinkUrl] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const { data: members } = useNotebookMembers(notebook.id, open)
  const { data: invites } = useNotebookInvites(notebook.id, open && isOwner)
  const createInvite = useCreateInvite(notebook.id)
  const revokeInvite = useRevokeInvite(notebook.id)
  const removeMember = useRemoveMember(notebook.id)

  const handleSendEmail = async () => {
    const trimmed = email.trim()
    if (!trimmed) return
    await createInvite.mutateAsync({ invite_type: 'email', email: trimmed })
    setEmail('')
  }

  const handleCreateLink = async () => {
    const invite = await createInvite.mutateAsync({ invite_type: 'link' })
    if (invite.invite_token) {
      setLinkUrl(`${window.location.origin}/notebooks/join?token=${invite.invite_token}`)
    }
  }

  const handleCopyLink = async () => {
    if (!linkUrl) return
    try {
      await navigator.clipboard.writeText(linkUrl)
      setCopied(true)
      toast({ title: t.common.success, description: t.collaboration.linkCopied })
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t.collaboration.shareNotebook}</DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
          {isOwner && (
            <>
              {/* Invite by email */}
              <div className="space-y-2">
                <p className="text-sm font-medium">{t.collaboration.inviteByEmail}</p>
                <div className="flex gap-2">
                  <Input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder={t.collaboration.emailPlaceholder}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleSendEmail()
                    }}
                  />
                  <Button
                    onClick={handleSendEmail}
                    disabled={!email.trim() || createInvite.isPending}
                  >
                    <Mail className="h-4 w-4 mr-2" />
                    {t.collaboration.sendInvite}
                  </Button>
                </div>
              </div>

              {/* Share link */}
              <div className="space-y-2">
                <p className="text-sm font-medium">{t.collaboration.shareLink}</p>
                {linkUrl ? (
                  <div className="flex gap-2">
                    <Input readOnly value={linkUrl} className="font-mono text-xs" />
                    <Button variant="outline" onClick={handleCopyLink}>
                      {copied ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="outline"
                    onClick={handleCreateLink}
                    disabled={createInvite.isPending}
                  >
                    <Link2 className="h-4 w-4 mr-2" />
                    {t.collaboration.createLink}
                  </Button>
                )}
              </div>

              {/* Pending invites */}
              {invites && invites.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">
                    {t.collaboration.pendingInvites}
                  </p>
                  <div className="space-y-1">
                    {invites.map((inv) => (
                      <div
                        key={inv.id}
                        className="flex items-center justify-between rounded-md border px-3 py-1.5 text-sm"
                      >
                        <span className="truncate">
                          {inv.invite_type === 'link'
                            ? t.collaboration.shareLink
                            : inv.email}
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => revokeInvite.mutate(inv.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                          <span className="sr-only">{t.collaboration.revoke}</span>
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <Separator />
            </>
          )}

          {/* Member roster */}
          <div className="space-y-2">
            <p className="text-sm font-medium">{t.collaboration.members}</p>
            <ScrollArea className="max-h-56">
              <div className="space-y-1">
                {(members ?? []).map((m) => (
                  <div
                    key={m.user_id}
                    className="flex items-center justify-between rounded-md px-3 py-1.5 text-sm"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="truncate">{m.email}</span>
                      <Badge variant={m.role === 'owner' ? 'default' : 'secondary'}>
                        {m.role === 'owner'
                          ? t.collaboration.owner
                          : t.collaboration.member}
                      </Badge>
                    </div>
                    {isOwner && m.role !== 'owner' && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => removeMember.mutate(m.user_id)}
                      >
                        <UserMinus className="h-4 w-4" />
                        <span className="sr-only">{t.collaboration.remove}</span>
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
