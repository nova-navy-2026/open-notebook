'use client'

import { Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getPageInfoContent, type PageInfoKey } from '@/lib/utils/page-info'

interface PageInfoButtonProps {
  pageKey: PageInfoKey
  className?: string
}

export function PageInfoButton({ pageKey, className }: PageInfoButtonProps) {
  const { language } = useTranslation()
  const content = getPageInfoContent(pageKey, language)

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={`h-10 w-10 text-muted-foreground hover:text-foreground ${className ?? ''}`}
          aria-label={content.title}
          title={content.title}
        >
          <Info className="h-6 w-6" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] w-full max-w-xl sm:max-w-xl p-0">
        <div className="flex max-h-[85vh] flex-col">
          <DialogHeader className="border-b px-6 py-5 pr-12">
            <DialogTitle>{content.title}</DialogTitle>
            {content.description && (
              <DialogDescription>{content.description}</DialogDescription>
            )}
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto px-6 py-5">
            <ul className="space-y-3 text-sm">
              {content.items.map((item, index) => (
                <li key={index} className="flex gap-3 leading-relaxed">
                  <span className="mt-2 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
