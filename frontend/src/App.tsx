import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { getToken } from './api'
import { RequireAuth } from './components/RequireAuth'
import { Data } from './pages/Data'
import { Login } from './pages/Login'
import { Profile } from './pages/Profile'
import { Week } from './pages/Week'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={getToken() ? <Navigate to="/week" replace /> : <Login />}
        />
        <Route
          path="/week"
          element={
            <RequireAuth>
              <Week />
            </RequireAuth>
          }
        />
        <Route
          path="/profile"
          element={
            <RequireAuth>
              <Profile />
            </RequireAuth>
          }
        />
        <Route
          path="/data"
          element={
            <RequireAuth>
              <Data />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/week" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
