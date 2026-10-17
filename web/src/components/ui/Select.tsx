import { cva, type VariantProps } from 'class-variance-authority'
import {
  Children,
  Fragment,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
} from 'react'
import { cn } from '@/lib/cn'
import { Icon } from '@/components/ui/Icon'

const triggerVariants = cva(
  'flex w-full items-center justify-between gap-2 border border-line bg-surface text-left text-ink hover:border-ink-muted/30 focus:border-ink-muted/40 focus:outline-none focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40',
  {
    variants: {
      size: {
        sm: 'h-control-sm px-2 text-caption',
        md: 'h-control-md px-3 text-body',
      },
    },
    defaultVariants: { size: 'md' },
  },
)

interface Option {
  value: string
  label: string
  disabled: boolean
}

function parseOptions(children: ReactNode): Option[] {
  const out: Option[] = []
  const walk = (nodes: ReactNode) => {
    Children.forEach(nodes, (child) => {
      if (!isValidElement(child)) return
      const el = child as ReactElement<{ value?: string | number; disabled?: boolean; children?: ReactNode }>
      if (el.type === Fragment) {
        walk(el.props.children)
        return
      }
      const label = Children.toArray(el.props.children).join('')
      out.push({ value: String(el.props.value ?? label), label, disabled: Boolean(el.props.disabled) })
    })
  }
  walk(children)
  return out
}

export interface SelectProps extends VariantProps<typeof triggerVariants> {
  value: string
  /** Same shape as a native select change event for the fields callers use. */
  onChange: (e: { target: { value: string }; currentTarget: { value: string } }) => void
  children: ReactNode
  id?: string
  className?: string
  disabled?: boolean
  'aria-label'?: string
  'aria-labelledby'?: string
}

interface Placement {
  left: number
  width: number
  top?: number
  bottom?: number
  maxHeight: number
}

/** Styled single-select listbox that replaces the browser's native menu. */
export function Select({ value, onChange, children, id, className, size, disabled, ...aria }: SelectProps) {
  const options = useMemo(() => parseOptions(children), [children])
  const selected = options.find((o) => o.value === value)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [place, setPlace] = useState<Placement | null>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const uid = useId()
  const listId = `${uid}-list`
  const typed = useRef({ text: '', at: 0 })

  const close = useCallback(() => setOpen(false), [])

  const openList = () => {
    if (disabled) return
    const idx = options.findIndex((o) => o.value === value)
    setActive(idx >= 0 ? idx : options.findIndex((o) => !o.disabled))
    setOpen(true)
  }

  const choose = (opt: Option | undefined) => {
    if (!opt || opt.disabled) return
    if (opt.value !== value) onChange({ target: { value: opt.value }, currentTarget: { value: opt.value } })
    setOpen(false)
    trigger.current?.focus()
  }

  useLayoutEffect(() => {
    if (!open || !trigger.current) return
    const r = trigger.current.getBoundingClientRect()
    const below = window.innerHeight - r.bottom - 8
    const above = r.top - 8
    const flip = below < 180 && above > below
    setPlace({
      left: r.left,
      width: r.width,
      ...(flip ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }),
      maxHeight: Math.max(120, Math.min(280, flip ? above : below)),
    })
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!trigger.current?.contains(t) && !list.current?.contains(t)) close()
    }
    const onMove = (e: Event) => {
      if (e.target instanceof Node && list.current?.contains(e.target)) return
      close()
    }
    document.addEventListener('mousedown', onDown)
    window.addEventListener('scroll', onMove, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('scroll', onMove, true)
      window.removeEventListener('resize', close)
    }
  }, [open, close])

  useEffect(() => {
    if (open) list.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  const step = (from: number, dir: 1 | -1) => {
    for (let i = from + dir; i >= 0 && i < options.length; i += dir) if (!options[i].disabled) return i
    return from
  }

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return
    if (e.key === 'Escape' && open) {
      e.preventDefault()
      e.stopPropagation()
      e.nativeEvent.stopImmediatePropagation()
      close()
      return
    }
    if (e.key === 'Tab') {
      close()
      return
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(e.key)) e.preventDefault()
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) openList()
      return
    }
    if (e.key === 'ArrowDown') setActive((a) => step(a, 1))
    else if (e.key === 'ArrowUp') setActive((a) => step(a, -1))
    else if (e.key === 'Home') setActive(step(-1, 1))
    else if (e.key === 'End') setActive(step(options.length, -1))
    else if (e.key === 'Enter' || e.key === ' ') choose(options[active])
    else if (e.key.length === 1) {
      const now = Date.now()
      typed.current = { text: (now - typed.current.at > 600 ? '' : typed.current.text) + e.key.toLowerCase(), at: now }
      const hit = options.findIndex((o) => !o.disabled && o.label.toLowerCase().startsWith(typed.current.text))
      if (hit >= 0) setActive(hit)
    }
  }

  return (
    <div className={cn('relative', className)}>
      <button
        ref={trigger}
        id={id}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && active >= 0 ? `${uid}-opt-${active}` : undefined}
        aria-label={aria['aria-label']}
        aria-labelledby={aria['aria-labelledby']}
        disabled={disabled}
        onClick={() => (open ? close() : openList())}
        onKeyDown={onKeyDown}
        className={triggerVariants({ size })}
      >
        <span className="min-w-0 flex-1 truncate">{selected?.label ?? ''}</span>
        <Icon name="chevronDown" className={cn('size-4 text-ink-muted transition-transform', open && 'rotate-180')} />
      </button>
      {open && place ? (
        <ul
          ref={list}
          id={listId}
          role="listbox"
          aria-label={aria['aria-label']}
          style={{ position: 'fixed', left: place.left, width: place.width, top: place.top, bottom: place.bottom, maxHeight: place.maxHeight }}
          className="z-[90] overflow-y-auto border border-line bg-surface py-1 shadow-lg"
        >
          {options.map((o, i) => (
            <li
              key={o.value}
              id={`${uid}-opt-${i}`}
              data-index={i}
              role="option"
              aria-selected={o.value === value}
              aria-disabled={o.disabled || undefined}
              onMouseEnter={() => !o.disabled && setActive(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(o)}
              className={cn(
                'flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-ink',
                size === 'sm' ? 'text-caption' : 'text-body',
                i === active && 'bg-surface-muted',
                o.value === value && 'font-medium',
                o.disabled && 'cursor-not-allowed opacity-40',
              )}
            >
              <span className="min-w-0 truncate">{o.label}</span>
              {o.value === value ? <Icon name="check" className="size-4 text-info" /> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
