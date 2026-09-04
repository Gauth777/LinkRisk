import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { PersistentPaymentsPanel } from './PersistentPaymentsPanel'

export function PersistentPaymentsPortal() {
  const [target, setTarget] = useState<HTMLElement | null>(null)

  useEffect(() => {
    const findTarget = () => {
      const overviewGrid = document.querySelector('.overview-main-grid')
      const overviewMain = overviewGrid?.closest('main.content') as HTMLElement | null
      setTarget((current) => current === overviewMain ? current : overviewMain)
    }

    findTarget()
    const observer = new MutationObserver(findTarget)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [])

  return target ? createPortal(<PersistentPaymentsPanel />, target) : null
}
