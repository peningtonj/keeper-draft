import { useEffect, useMemo, useState } from 'react'
import './App.css'
import playersCacheUrl from '../server/cache/players.json?url'
import yearsCacheUrl from '../server/cache/years.json?url'

type Player = {
  id: number | null
  name: string
  team: string | null
  positions: string[]
  previousGames: number | null
  previousAverage: number | null
  previousTotal: number | null
  price: number | null
  status: string | null
  statusText: string | null
  locked: boolean | null
  active: boolean | null
  yearsPlaying: number | null
  firstYear: number | null
  ageYears: number | null
  lastFiveSeasons?: Array<{ season: number; games: number; average: number | null }>
  lastFiveGames?: number | null
  lastFiveAverage?: number | null
}

type ApiResponse = {
  updatedAt: string
  year: number
  players: Player[]
  count: number
}

type YearsCache = Record<string, { yearsPlaying: number | null; firstYear: number | null; ageYears: number | null }>

const STORAGE_KEY = 'keeper-players-cache-v2'
const DRAFT_KEY = 'keeper-draft-status-v1'
const ASSIGN_KEY = 'keeper-position-assignments-v1'
const SHORTLIST_KEY = 'keeper-shortlist-v1'
const SHORTLIST_NOTES_KEY = 'keeper-shortlist-notes-v1'

type DraftStatus = 'mine' | 'unavailable' | null

type DraftMap = Record<string, DraftStatus>
type AssignmentMap = Record<string, string>
type ShortlistMap = Record<string, boolean>
type ShortlistNotesMap = Record<string, string>

const normalizePlayerKey = (name: string) => {
  const cleaned = name
    .replace(/’/g, "'")
    .replace(/\./g, ' ')
    .replace(/-/g, ' ')
    .replace(/\u00a0/g, ' ')
  const normalized = cleaned.toLowerCase().split(/\s+/).filter(Boolean).join(' ')
  return normalized.replace(/\b(jr|junior)\b/g, '').trim().replace(/\s+/g, ' ')
}

const cacheKey = (name: string, team: string | null) =>
  `${normalizePlayerKey(name)}|${(team ?? '').toLowerCase()}`

const mergeYearsCache = (players: Player[], yearsCache: YearsCache | null) => {
  if (!yearsCache) return players
  return players.map((player) => {
    const key = cacheKey(player.name, player.team)
    const cached = yearsCache[key]
    if (!cached) return player
    return {
      ...player,
      yearsPlaying: cached.yearsPlaying ?? player.yearsPlaying ?? null,
      firstYear: cached.firstYear ?? player.firstYear ?? null,
      ageYears: cached.ageYears ?? player.ageYears ?? null,
    }
  })
}

function App() {
  const [players, setPlayers] = useState<Player[]>([])
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [year, setYear] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [position, setPosition] = useState('All')
  const [team, setTeam] = useState('All')
  const [ageCategory, setAgeCategory] = useState('Free Agents (Any Age)')
  const [showFitsOnly, setShowFitsOnly] = useState(true)
  const [draftMap, setDraftMap] = useState<DraftMap>({})
  const [assignments, setAssignments] = useState<AssignmentMap>({})
  const [shortlistMap, setShortlistMap] = useState<ShortlistMap>({})
  const [shortlistNotes, setShortlistNotes] = useState<ShortlistNotesMap>({})
  const [showShortlist, setShowShortlist] = useState(false)
  const [expandedShortlist, setExpandedShortlist] = useState<Record<string, boolean>>({})
  const [sortKey, setSortKey] = useState<
    | 'name'
    | 'team'
    | 'positions'
    | 'firstYear'
    | 'price'
    | 'previousAverage'
    | 'previousGames'
    | 'status'
  >('price')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')

  useEffect(() => {
    document.title = 'Keeper League Draft Board'
    const cached = localStorage.getItem(STORAGE_KEY)
    if (cached) {
      try {
        const parsed = JSON.parse(cached) as ApiResponse
        const merged = mergeYearsCache(parsed.players, null)
        setPlayers(merged)
        setUpdatedAt(parsed.updatedAt)
        setYear(parsed.year)
        const hasStatspack = parsed.players.some(
          (player) =>
            Array.isArray(player.lastFiveSeasons) && player.lastFiveSeasons.length > 0
        )
        const hasYears = parsed.players.some(
          (player) => player.firstYear !== null || player.ageYears !== null
        )
        if (hasStatspack && hasYears) {
          return
        }
      } catch {
        localStorage.removeItem(STORAGE_KEY)
      }
    }

    const loadStaticCache = async () => {
      try {
        const [playersResponse, yearsResponse] = await Promise.all([
          fetch(playersCacheUrl),
          fetch(yearsCacheUrl),
        ])
        if (!playersResponse.ok) {
          throw new Error('Unable to load cached player data.')
        }
        const data = (await playersResponse.json()) as ApiResponse
        const yearsCache = yearsResponse.ok ? ((await yearsResponse.json()) as YearsCache) : null
        const merged = mergeYearsCache(data.players, yearsCache)
        const nextPayload = { ...data, players: merged }
        setPlayers(merged)
        setUpdatedAt(data.updatedAt)
        setYear(data.year)
        localStorage.setItem(STORAGE_KEY, JSON.stringify(nextPayload))
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : 'No cached data available. Add players.json to the build.'
        )
      }
    }

    void loadStaticCache()
  }, [])

  useEffect(() => {
    const savedDraft = localStorage.getItem(DRAFT_KEY)
    if (savedDraft) {
      try {
        setDraftMap(JSON.parse(savedDraft) as DraftMap)
      } catch {
        localStorage.removeItem(DRAFT_KEY)
      }
    }
    const savedAssignments = localStorage.getItem(ASSIGN_KEY)
    if (savedAssignments) {
      try {
        setAssignments(JSON.parse(savedAssignments) as AssignmentMap)
      } catch {
        localStorage.removeItem(ASSIGN_KEY)
      }
    }
    const savedShortlist = localStorage.getItem(SHORTLIST_KEY)
    if (savedShortlist) {
      try {
        setShortlistMap(JSON.parse(savedShortlist) as ShortlistMap)
      } catch {
        localStorage.removeItem(SHORTLIST_KEY)
      }
    }
    const savedNotes = localStorage.getItem(SHORTLIST_NOTES_KEY)
    if (savedNotes) {
      try {
        setShortlistNotes(JSON.parse(savedNotes) as ShortlistNotesMap)
      } catch {
        localStorage.removeItem(SHORTLIST_NOTES_KEY)
      }
    }
  }, [])

  const positions = useMemo(() => {
    const list = Array.from(
      new Set(players.flatMap((player) => player.positions).filter(Boolean))
    ).sort()
    return ['All', ...list]
  }, [players])

  const teams = useMemo(() => {
    const list = Array.from(new Set(players.map((player) => player.team).filter(Boolean)))
      .map((value) => value as string)
      .sort()
    return ['All', ...list]
  }, [players])

  const seasonYear = year ?? new Date().getFullYear()

  const getAgeSlot = (player: Player) => {
    if (player.ageYears !== null && player.ageYears >= 30) {
      return 'senior'
    }
    const draftYear = player.firstYear
    if (draftYear === seasonYear - 1) return 'year1'
    if (draftYear === seasonYear - 2) return 'year2'
    if (draftYear === seasonYear - 3) return 'year3'
    if (draftYear === seasonYear - 4) return 'year4'
    return 'free'
  }

  const getDraftStatusLabel = (player: Player) => {
    if (player.ageYears !== null && player.ageYears >= 30) {
      return 'Snr'
    }
    const draftYear = player.firstYear
    if (draftYear === null || draftYear === undefined) {
      return 'FA'
    }
    if (draftYear === seasonYear - 1) return '1st'
    if (draftYear === seasonYear - 2) return '2nd'
    if (draftYear === seasonYear - 3) return '3rd'
    if (draftYear === seasonYear - 4) return '4th'
    return 'FA'
  }

  const formatDraftYearWithStatus = (player: Player) => {
    const yearText = player.firstYear ?? '—'
    const statusText = getDraftStatusLabel(player)
    return `${yearText} (${statusText})`
  }

  const getDraftKeys = (player: Player) => {
    const name = player.name.trim()
    const teamName = (player.team ?? '').trim()
    const primary = `${name}|${teamName}`.toLowerCase()
    const legacy = String(player.id ?? player.name)
    const nameOnly = name.toLowerCase()
    return { primary, legacy, nameOnly }
  }

  const draftStatusFor = (player: Player) => {
    const keys = getDraftKeys(player)
    return draftMap[keys.primary] ?? draftMap[keys.legacy] ?? draftMap[keys.nameOnly] ?? null
  }

  const formatTeamAbbrev = (teamValue: string | null) => {
    if (!teamValue) return '—'
    const cleaned = teamValue.replace(/[^A-Za-z]/g, '')
    if (!cleaned) return '—'
    if (cleaned.length <= 3) return cleaned.toUpperCase()
    return cleaned.slice(0, 3).toUpperCase()
  }

  const formatPrice = (priceValue: number | null) =>
    priceValue ? `$${priceValue.toLocaleString()}` : '—'

  const assignedPositionFor = (player: Player) => {
    const keys = getDraftKeys(player)
    return assignments[keys.primary] ?? assignments[keys.legacy] ?? assignments[keys.nameOnly]
  }

  const isShortlisted = (player: Player) => {
    const keys = getDraftKeys(player)
    return Boolean(shortlistMap[keys.primary] ?? shortlistMap[keys.legacy] ?? shortlistMap[keys.nameOnly])
  }

  const updateShortlist = (player: Player, nextValue: boolean) => {
    const keys = getDraftKeys(player)
    const next = { ...shortlistMap }
    delete next[keys.legacy]
    delete next[keys.nameOnly]
    if (nextValue) {
      next[keys.primary] = true
    } else {
      delete next[keys.primary]
    }
    setShortlistMap(next)
    localStorage.setItem(SHORTLIST_KEY, JSON.stringify(next))
  }

  const updateShortlistNote = (player: Player, value: string) => {
    const keys = getDraftKeys(player)
    const next = { ...shortlistNotes, [keys.primary]: value }
    delete next[keys.legacy]
    delete next[keys.nameOnly]
    if (!value.trim()) {
      delete next[keys.primary]
    }
    setShortlistNotes(next)
    localStorage.setItem(SHORTLIST_NOTES_KEY, JSON.stringify(next))
  }

  const isShortlistExpanded = (player: Player) => {
    const key = getDraftKeys(player).primary
    return Boolean(expandedShortlist[key])
  }

  const toggleShortlistExpanded = (player: Player) => {
    const key = getDraftKeys(player).primary
    setExpandedShortlist((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const updateAssignment = (player: Player, positionValue: string) => {
    const keys = getDraftKeys(player)
    const next = { ...assignments, [keys.primary]: positionValue }
    delete next[keys.legacy]
    delete next[keys.nameOnly]
    setAssignments(next)
    localStorage.setItem(ASSIGN_KEY, JSON.stringify(next))
  }

  const updateDraftStatus = (player: Player, status: DraftStatus) => {
    const keys = getDraftKeys(player)
    const next = { ...draftMap }
    delete next[keys.legacy]
    delete next[keys.nameOnly]

    if (status === null) {
      delete next[keys.primary]
      const nextAssignments = { ...assignments }
      delete nextAssignments[keys.primary]
      delete nextAssignments[keys.legacy]
      delete nextAssignments[keys.nameOnly]
      setAssignments(nextAssignments)
      localStorage.setItem(ASSIGN_KEY, JSON.stringify(nextAssignments))
    } else {
      next[keys.primary] = status
      if (status === 'mine') {
        updateShortlist(player, true)
      }
    }

    setDraftMap(next)
    localStorage.setItem(DRAFT_KEY, JSON.stringify(next))
  }

  const myTeamPlayers = useMemo(
    () => players.filter((player) => draftStatusFor(player) === 'mine'),
    [players, draftMap]
  )

  const shortlistPlayers = useMemo(
    () => players.filter((player) => isShortlisted(player)),
    [players, shortlistMap]
  )

  useEffect(() => {
    if (!showShortlist) return
    const adjustHeights = () => {
      document.querySelectorAll<HTMLTextAreaElement>('.shortlist-notes').forEach((el) => {
        el.style.height = 'auto'
        el.style.height = `${el.scrollHeight}px`
      })
    }
    const raf = window.requestAnimationFrame(adjustHeights)
    return () => window.cancelAnimationFrame(raf)
  }, [showShortlist, shortlistPlayers, shortlistNotes])

  const computeTeamSlots = () => {
    const limits = { DEF: 3, MID: 4, RUC: 1, FWD: 3, BENCH: 5 }
    const counts = { DEF: 0, MID: 0, RUC: 0, FWD: 0, BENCH: 0 }
    const resolvedAssignments: Record<string, string> = {}

    for (const player of myTeamPlayers) {
      const key = getDraftKeys(player).primary
      const availablePositions = player.positions.length ? [...player.positions] : []
      const preferred = assignedPositionFor(player)
      let chosen: string | null = null

      if (preferred) {
        if (preferred === 'BENCH') {
          chosen = 'BENCH'
        } else if (
          preferred in counts &&
          counts[preferred as keyof typeof counts] < limits[preferred as keyof typeof limits]
        ) {
          chosen = preferred
        } else {
          chosen = 'BENCH'
        }
      }

      if (!chosen) {
        for (const positionKey of availablePositions) {
          if (positionKey in counts && counts[positionKey as keyof typeof counts] < limits[positionKey as keyof typeof limits]) {
            chosen = positionKey
            break
          }
        }
      }

      if (!chosen) {
        chosen = 'BENCH'
      }

      if (!chosen) {
        chosen = availablePositions[0] ?? 'BENCH'
      }

      if (chosen in counts) {
        counts[chosen as keyof typeof counts] += 1
      }
      resolvedAssignments[key] = chosen
    }

    const ageLimits = {
      year1: 2,
      year2: 2,
      year3: 2,
      year4: 2,
      free: 6,
      senior: 2,
    }
    const ageCounts = { year1: 0, year2: 0, year3: 0, year4: 0, free: 0, senior: 0 }
    for (const player of myTeamPlayers) {
      const slot = getAgeSlot(player)
      if (slot !== 'free' && ageCounts[slot] >= ageLimits[slot] && ageCounts.free < ageLimits.free) {
        ageCounts.free += 1
      } else {
        ageCounts[slot] += 1
      }
    }

    return { limits, counts, ageLimits, ageCounts, resolvedAssignments }
  }

  const teamSlots = useMemo(computeTeamSlots, [myTeamPlayers, seasonYear, assignments])

  const fitsMyTeam = (player: Player) => {
    const { limits, counts, ageLimits, ageCounts } = teamSlots
    if (draftStatusFor(player) !== null) {
      return false
    }

    const ageSlot = getAgeSlot(player)
    const canUseAgeSlot = ageCounts[ageSlot] < ageLimits[ageSlot]
    const canUseFreeSlot = ageCounts.free < ageLimits.free
    if (!canUseAgeSlot && !(ageSlot !== 'free' && canUseFreeSlot)) {
      return false
    }

    let hasPositionSlot = false
    for (const positionKey of player.positions) {
      if (positionKey in counts && counts[positionKey as keyof typeof counts] < limits[positionKey as keyof typeof limits]) {
        hasPositionSlot = true
        break
      }
    }
    const benchAvailable = counts.BENCH < limits.BENCH
    return hasPositionSlot || benchAvailable
  }

  const filteredPlayers = useMemo(() => {
    const filtered = players.filter((player) => {
      const matchesSearch = player.name.toLowerCase().includes(search.toLowerCase())
      const matchesPosition = position === 'All' || player.positions.includes(position)
      const matchesTeam = team === 'All' || player.team === team
      const matchesAgeCategory = (() => {
        if (ageCategory === 'Free Agents (Any Age)') {
          return true
        }
        const firstYear = player.firstYear
        if (ageCategory === '1st Year') {
          return firstYear === seasonYear - 1
        }
        if (ageCategory === '2nd Year') {
          return firstYear === seasonYear - 2
        }
        if (ageCategory === '3rd Year') {
          return firstYear === seasonYear - 3
        }
        if (ageCategory === '4th Year') {
          return firstYear === seasonYear - 4
        }
        if (ageCategory === 'Senior (30+)') {
          return player.ageYears !== null && player.ageYears >= 30
        }
        return true
      })()
      const matchesFit = !showFitsOnly || fitsMyTeam(player)
      const isAvailable = draftStatusFor(player) === null
      return matchesSearch && matchesPosition && matchesTeam && matchesAgeCategory && matchesFit && isAvailable
    })
    const sorted = [...filtered].sort((a, b) => {
      const direction = sortDirection === 'asc' ? 1 : -1
      const valueA = (() => {
        switch (sortKey) {
          case 'name':
            return a.name
          case 'team':
            return a.team ?? ''
          case 'positions':
            return a.positions.join('/')
          case 'firstYear':
            return a.firstYear ?? -1
          case 'price':
            return a.price ?? -1
          case 'previousAverage':
            return a.previousAverage ?? -1
          case 'previousGames':
            return a.previousGames ?? -1
          case 'status':
            return a.statusText ?? a.status ?? ''
          default:
            return ''
        }
      })()
      const valueB = (() => {
        switch (sortKey) {
          case 'name':
            return b.name
          case 'team':
            return b.team ?? ''
          case 'positions':
            return b.positions.join('/')
          case 'firstYear':
            return b.firstYear ?? -1
          case 'price':
            return b.price ?? -1
          case 'previousAverage':
            return b.previousAverage ?? -1
          case 'previousGames':
            return b.previousGames ?? -1
          case 'status':
            return b.statusText ?? b.status ?? ''
          default:
            return ''
        }
      })()
      if (typeof valueA === 'number' && typeof valueB === 'number') {
        return (valueA - valueB) * direction
      }
      return String(valueA).localeCompare(String(valueB)) * direction
    })
    return sorted
  }, [players, search, position, team, ageCategory, year, sortKey, sortDirection, showFitsOnly, draftMap, teamSlots])

  const sortOptions: Array<{ value: 'name' | 'price'; label: string }> = [
    { value: 'name', label: 'Name' },
    { value: 'price', label: 'Price' },
  ]

  const updatedLabel = updatedAt ? new Date(updatedAt).toLocaleString() : 'Not loaded'

  return (
    <div className="app">
      <header className="hero">
        <div>
          <p className="eyebrow">Super Coach Keeper League</p>
          <h1>Draft Board</h1>
          <p className="subtext">
            Filter available players by position and review recent SuperCoach output. Click the
            tick button to draft a player to your team, or the cross button to mark them as unavailable (drafted by someone else).
          </p>
        </div>
        <div className="summary">
          <div>
            <span>Total Players</span>
            <strong>{players.length}</strong>
          </div>
          <div>
            <span>Filtered</span>
            <strong>{filteredPlayers.length}</strong>
          </div>
          <div>
            <span>Season Year</span>
            <strong>{year ?? '—'}</strong>
          </div>
          <div>
            <span>Last Updated</span>
            <strong>{updatedLabel}</strong>
          </div>
        </div>
      </header>

      <section className="controls">
        <div className="control">
          <label htmlFor="search">Search</label>
          <input
            id="search"
            type="search"
            placeholder="Search by player name"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="control">
          <label htmlFor="position">Position</label>
          <select
            id="position"
            value={position}
            onChange={(event) => setPosition(event.target.value)}
          >
            {positions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
        <div className="control">
          <label htmlFor="team">Team</label>
          <select id="team" value={team} onChange={(event) => setTeam(event.target.value)}>
            {teams.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
        <div className="control">
          <label htmlFor="age-category">Age Category</label>
          <select
            id="age-category"
            value={ageCategory}
            onChange={(event) => setAgeCategory(event.target.value)}
          >
            {
              [
                'Free Agents (Any Age)',
                '1st Year',
                '2nd Year',
                '3rd Year',
                '4th Year',
                'Senior (30+)',
              ].map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))
            }
          </select>
        </div>
        <div className="control">
          <label htmlFor="sort-by">Sort By</label>
          <select
            id="sort-by"
            value={sortKey}
            onChange={(event) => {
              const nextValue = event.target.value as 'name' | 'price'
              setSortKey(nextValue)
              setSortDirection(nextValue === 'price' ? 'desc' : 'asc')
            }}
          >
            {sortOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="control toggle">
          <label>Order</label>
          <button
            type="button"
            onClick={() => setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'))}
          >
            {sortDirection === 'asc' ? 'Ascending' : 'Descending'}
          </button>
        </div>
        <div className="control toggle">
          <label>Draft</label>
          <button
            type="button"
            onClick={() => {
              setDraftMap({})
              setAssignments({})
              localStorage.removeItem(DRAFT_KEY)
              localStorage.removeItem(ASSIGN_KEY)
            }}
          >
            Reset Draft
          </button>
        </div>
        <div className="control toggle">
          <label>Shortlist</label>
          <button
            type="button"
            onClick={() => setShowShortlist((prev) => !prev)}
          >
            {showShortlist ? 'Hide Shortlist' : `Show Shortlist (${shortlistPlayers.length})`}
          </button>
        </div>
        <button className="primary" type="button" disabled>
          Static Data
        </button>
      </section>

      {error && <div className="error">{error}</div>}

      {showShortlist && (
        <aside className="shortlist-drawer">
          <div className="shortlist-drawer-header">
            <div>
              <h2>Shortlist</h2>
              <span>{shortlistPlayers.length} players</span>
            </div>
            <button
              type="button"
              className="icon-btn danger"
              aria-label="Close shortlist"
              onClick={() => setShowShortlist(false)}
            >
              ✕
            </button>
          </div>
          {shortlistPlayers.length === 0 ? (
            <p className="loading">No players shortlisted yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>Pos</th>
                  <th>Category</th>
                  <th>Price</th>
                  <th>2025 Games</th>
                  <th>2025 Avg</th>
                  <th>Last 5 Seasons Games</th>
                  <th>Last 5 Seasons Avg</th>
                  <th>Status</th>
                  <th>Notes</th>
                  <th></th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {shortlistPlayers.map((player) => (
                  <>
                    <tr key={`shortlist-${player.id}-${player.name}`}>
                      <td>
                        <div className="cell-title">{player.name}</div>
                        <div className="cell-sub">{player.team ?? '—'}</div>
                      </td>
                      <td>{player.positions.length ? player.positions.join('/') : '—'}</td>
                      <td>{getDraftStatusLabel(player)}</td>
                      <td>{formatPrice(player.price)}</td>
                      <td>{player.previousGames ?? '—'}</td>
                      <td>{player.previousAverage ?? '—'}</td>
                      <td>{player.lastFiveGames ?? '—'}</td>
                      <td>{player.lastFiveAverage ?? '—'}</td>
                      <td>{player.statusText ?? player.status ?? '—'}</td>
                      <td>
                        <textarea
                          className="shortlist-notes"
                          placeholder="Notes"
                          rows={1}
                          value={shortlistNotes[getDraftKeys(player).primary] ?? ''}
                          onChange={(event) => updateShortlistNote(player, event.target.value)}
                          onInput={(event) => {
                            const target = event.currentTarget
                            target.style.height = 'auto'
                            target.style.height = `${target.scrollHeight}px`
                          }}
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="icon-btn"
                          title="Toggle last five seasons"
                          onClick={() => toggleShortlistExpanded(player)}
                        >
                          {isShortlistExpanded(player) ? '▾' : '▸'}
                        </button>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="icon-btn danger"
                          title="Remove from shortlist"
                          onClick={() => updateShortlist(player, false)}
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                    {isShortlistExpanded(player) && (
                      <tr key={`shortlist-detail-${player.id}-${player.name}`} className="shortlist-detail">
                        <td colSpan={11}>
                          <div className="shortlist-detail-grid">
                            {(player.lastFiveSeasons?.length
                              ? player.lastFiveSeasons
                              : []
                            ).map((season) => (
                              <div key={`${player.id}-${season.season}`} className="shortlist-detail-card">
                                <strong>{season.season}</strong>
                                <span>{season.games} games</span>
                                <span>{season.average ?? '—'} avg</span>
                              </div>
                            ))}
                            {!player.lastFiveSeasons?.length && (
                              <span className="cell-sub">No last five seasons data.</span>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          )}
        </aside>
      )}

      <section className="main-layout">
        <div className="table-wrapper">
          <h2>My Team</h2>
          <div className="summary">
            <div>
              <span>1st Year</span>
              <strong>{teamSlots.ageCounts.year1} / {teamSlots.ageLimits.year1}</strong>
            </div>
            <div>
              <span>2nd Year</span>
              <strong>{teamSlots.ageCounts.year2} / {teamSlots.ageLimits.year2}</strong>
            </div>
            <div>
              <span>3rd Year</span>
              <strong>{teamSlots.ageCounts.year3} / {teamSlots.ageLimits.year3}</strong>
            </div>
            <div>
              <span>4th Year</span>
              <strong>{teamSlots.ageCounts.year4} / {teamSlots.ageLimits.year4}</strong>
            </div>
            <div>
              <span>Free Agents</span>
              <strong>{teamSlots.ageCounts.free} / {teamSlots.ageLimits.free}</strong>
            </div>
            <div>
              <span>Senior (30+)</span>
              <strong>{teamSlots.ageCounts.senior} / {teamSlots.ageLimits.senior}</strong>
            </div>
          </div>
          <div className="formation">
            {(['DEF', 'MID', 'RUC', 'FWD', 'BENCH'] as const).map((slot) => (
              <div key={slot} className="formation-row">
                <h3
                  className={
                    slot === 'BENCH' && teamSlots.counts.BENCH > teamSlots.limits.BENCH
                      ? 'over-limit'
                      : undefined
                  }
                >
                  {slot} ({teamSlots.counts[slot]} / {teamSlots.limits[slot]})
                </h3>
                <div className="tile-row">
                  {myTeamPlayers
                    .filter(
                      (player) =>
                        (teamSlots.resolvedAssignments[getDraftKeys(player).primary] ?? 'BENCH') ===
                        slot
                    )
                    .map((player) => (
                      <div key={`tile-${player.id}-${player.name}`} className="player-tile">
                        <div className="tile-header">
                          <span>{player.name}</span>
                          <button type="button" onClick={() => updateDraftStatus(player, null)}>
                            ×
                          </button>
                        </div>
                        <div className="tile-meta">
                          <span>{player.team ?? '—'}</span>
                          <span>
                            {player.positions.length ? player.positions.join('/') : '—'}
                          </span>
                          <span>Draft {formatDraftYearWithStatus(player)}</span>
                          <span>Age {player.ageYears ?? '—'}</span>
                        </div>
                        <select
                          value={
                            teamSlots.resolvedAssignments[getDraftKeys(player).primary] ?? 'BENCH'
                          }
                          onChange={(event) => updateAssignment(player, event.target.value)}
                        >
                          {[...(player.positions.length ? player.positions : []), 'BENCH'].map((option) => (
                            <option key={`${player.name}-${option}`} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </div>
                    ))}
                </div>
              </div>
            ))}
          </div>
          {myTeamPlayers.length === 0 && <p className="loading">No players drafted yet.</p>}
        </div>

        <div className="table-wrapper">
          <div className="table-header">
            <h2>{showFitsOnly ? 'Player List (Eligible in My Team)' : 'Player List'}</h2>
            <div className="table-actions">
              <button
                type="button"
                className="mini-toggle"
                onClick={() => setShowFitsOnly((prev) => !prev)}
              >
                {showFitsOnly ? 'Show All Available' : 'Show Fits My Team'}
              </button>
            </div>
          </div>
          <table>
            <thead>
              <tr>
                <th>Player</th>
                <th>Draft Year</th>
                <th className="last-five-col">Last 5 Seasons Average</th>
                <th>Draft</th>
              </tr>
            </thead>
            <tbody>
              {filteredPlayers.map((player) => (
                <tr key={`${player.id}-${player.name}`}>
                  <td className="compact-cell">
                    <div className="cell-title">{player.name}</div>
                    <div className="cell-sub">
                      {formatTeamAbbrev(player.team)} · {formatPrice(player.price)} ·
                      {player.positions.length ? player.positions.join('/') : '—'} ·
                      Age {player.ageYears ?? '—'}
                    </div>
                  </td>
                  <td>{formatDraftYearWithStatus(player)}</td>
                  <td className="last-five-col">
                    {player.lastFiveSeasons && player.lastFiveSeasons.length > 0 ? (
                      <div className="stacked-stat">
                        <span>
                          {(
                            player.lastFiveSeasons.reduce(
                              (total, season) => total + (season.games ?? 0),
                              0
                            ) / player.lastFiveSeasons.length
                          ).toFixed(1)}{' '}
                          games
                        </span>
                        <span>{player.lastFiveAverage ?? '—'} points</span>
                      </div>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>
                    <div className="row-actions">
                      <button
                        type="button"
                        className="icon-btn success"
                        title="Draft to my team"
                        onClick={() => updateDraftStatus(player, 'mine')}
                      >
                        ✓
                      </button>
                      <button
                        type="button"
                        className="icon-btn danger"
                        title="Mark as taken"
                        onClick={() => updateDraftStatus(player, 'unavailable')}
                      >
                        ✕
                      </button>
                      <button
                        type="button"
                        className={`icon-btn shortlist ${isShortlisted(player) ? 'active' : ''}`}
                        title={isShortlisted(player) ? 'Remove from shortlist' : 'Add to shortlist'}
                        onClick={() => updateShortlist(player, !isShortlisted(player))}
                      >
                        ★
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filteredPlayers.length === 0 && (
            <p className="loading">No players match these filters.</p>
          )}
        </div>
      </section>
    </div>
  )
}

export default App
