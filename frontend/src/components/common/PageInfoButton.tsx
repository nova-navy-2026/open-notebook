'use client'

import { Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
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
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={`h-7 w-7 text-muted-foreground hover:text-foreground ${className ?? ''}`}
          aria-label={content.title}
          title={content.title}
        >
          <Info className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 max-w-[90vw]">
        <div className="space-y-2">
          <p className="text-sm font-semibold">{content.title}</p>
          {content.description && (
            <p className="text-xs text-muted-foreground">{content.description}</p>
          )}
          <ul className="space-y-1.5 text-xs">
            {content.items.map((item, index) => (
              <li key={index} className="flex gap-2">
                <span className="text-primary mt-px">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </PopoverContent>
    </Popover>
  )
}
