'use client'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Bell, Check, X } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useMyInvites, useRespondToInvite } from '@/lib/hooks/use-collaboration'

export function InvitesInbox() {
  const { t } = useTranslation()
  const { data: invites } = useMyInvites()
  const { accept, decline } = useRespondToInvite()

  const count = invites?.length ?? 0

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="relative"
          aria-label={t.collaboration.notifications}
        >
          <Bell className="h-4 w-4" />
          {count > 0 && (
            <Badge
              variant="destructive"
              className="absolute -top-2 -right-2 h-5 min-w-5 px-1 text-[10px] leading-none flex items-center justify-center"
            >
              {count}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="border-b px-4 py-2 text-sm font-medium">
          {t.collaboration.notifications}
        </div>
        {count === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-muted-foreground">
            {t.collaboration.noInvitations}
          </div>
        ) : (
          <div className="max-h-80 overflow-y-auto divide-y">
            {invites!.map((inv) => (
              <div key={inv.id} className="px-4 py-3 space-y-2">
                <p className="text-sm">
                  <span className="font-medium">{inv.notebook_name ?? inv.notebook_id}</span>
                  <br />
                  <span className="text-muted-foreground">
                    {inv.invited_by_email
                      ? `${inv.invited_by_email} ${t.collaboration.invitedYou}`
                      : t.collaboration.invitedYou}
                  </span>
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => accept.mutate(inv.id)}
                    disabled={accept.isPending}
                  >
                    <Check className="h-4 w-4 mr-1" />
                    {t.collaboration.accept}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => decline.mutate(inv.id)}
                    disabled={decline.isPending}
                  >
                    <X className="h-4 w-4 mr-1" />
                    {t.collaboration.decline}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
