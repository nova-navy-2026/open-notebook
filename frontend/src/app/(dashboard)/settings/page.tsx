'use client'

import { SettingsForm } from './components/SettingsForm'
import { useSettings } from '@/lib/hooks/use-settings'
import { Button } from '@/components/ui/button'
import { RefreshCw } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'

export default function SettingsPage() {
  const { t } = useTranslation()
  const { refetch } = useSettings()

  return (
      <div className="w-full h-full flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <div className="p-4 sm:p-6 lg:p-8">
              <div className="max-w-6xl mx-auto">
              <div className="flex items-center gap-4 mb-6">
                <h1 className="text-2xl sm:text-3xl font-bold">{t.navigation.settings}</h1>
                <Button variant="outline" size="sm" onClick={() => refetch()}>
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </div>

              <SettingsForm />
            </div>
          </div>
        </div>
      </div>
  )
}
