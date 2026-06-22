'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { collaborationApi } from '@/lib/api/collaboration'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useToast } from '@/lib/hooks/use-toast'
import { getApiErrorMessage } from '@/lib/utils/error-handler'

function JoinByLink() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get('token')
  const [error, setError] = useState<string | null>(null)
  const attempted = useRef(false)

  useEffect(() => {
    if (attempted.current) return
    attempted.current = true

    if (!token) {
      router.replace('/notebooks')
      return
    }

    collaborationApi
      .acceptLink(token)
      .then((res) => {
        toast({ title: t.common.success, description: t.collaboration.joinedNotebook })
        router.replace(`/notebooks/${encodeURIComponent(res.notebook_id)}`)
      })
      .catch((err) => {
        setError(getApiErrorMessage(err, (key) => t(key), 'common.error'))
      })
  }, [token, router, toast, t])

  if (error) {
    return (
      <div className="p-8 text-center">
        <p className="text-destructive">{error}</p>
      </div>
    )
  }

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center gap-4">
      <LoadingSpinner size="lg" />
      <p className="text-muted-foreground">{t.collaboration.joining}</p>
    </div>
  )
}

export default function JoinNotebookPage() {
  return (
    <Suspense fallback={<LoadingSpinner size="lg" />}>
      <JoinByLink />
    </Suspense>
  )
}
