import { Moon, Sun } from 'lucide-react'
import { NavLink, useNavigate } from 'react-router-dom'
import { clearToken } from '../api'
import { useTheme } from '../theme'

export function Nav() {
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()

  function signOut() {
    clearToken()
    navigate('/login')
  }

  return (
    <header className="nav">
      <div className="nav-inner">
        <NavLink to="/week" className="nav-wordmark">
          coach
        </NavLink>
        <nav className="nav-links">
          <NavLink to="/week" className="nav-link">
            Week
          </NavLink>
          <NavLink to="/profile" className="nav-link">
            Profile
          </NavLink>
          <NavLink to="/data" className="nav-link">
            Data
          </NavLink>
        </nav>
        <div className="nav-right">
          <button
            type="button"
            className="icon-button"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
          >
            {theme === 'dark' ? <Sun size={20} strokeWidth={1.5} /> : <Moon size={20} strokeWidth={1.5} />}
          </button>
          <button type="button" className="button button-secondary button-compact" onClick={signOut}>
            Sign out
          </button>
        </div>
      </div>
    </header>
  )
}
