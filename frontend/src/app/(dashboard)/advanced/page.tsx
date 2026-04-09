'use client'

import { RebuildEmbeddings } from './components/RebuildEmbeddings'
import { SystemInfo } from './components/SystemInfo'
import { useTranslation } from '@/lib/hooks/use-translation'

export default function AdvancedPage() {
  const { t } = useTranslation()
  return (
      <div className="w-full h-full flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <div className="p-4 sm:p-6 lg:p-8">
              <div className="max-w-6xl mx-auto space-y-6">
              <div>
                <h1 className="text-3xl sm:text-4xl font-bold">{t.advanced.title}</h1>
                <p className="text-muted-foreground mt-2">
                  {t.advanced.desc}
                </p>
              </div>

              <SystemInfo />
              <RebuildEmbeddings />
            </div>
          </div>
        </div>
      </div>
  )
}
