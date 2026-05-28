import { Routes, Route, Navigate } from 'react-router-dom'
import Navbar from './components/Navbar'
import ExecutiveSummary from './pages/ExecutiveSummary'
import AnalyticalCharts from './pages/AnalyticalCharts'
import Segments from './pages/Segments'
import Recommendations from './pages/Recommendations'

export default function App() {
  return (
    <>
      <Navbar />
      <main className="main-content">
        <Routes>
          <Route path="/"               element={<Navigate to="/summary" replace />} />
          <Route path="/summary"        element={<ExecutiveSummary />} />
          <Route path="/charts"         element={<AnalyticalCharts />} />
          <Route path="/segments"       element={<Segments />} />
          <Route path="/recommendations" element={<Recommendations />} />
        </Routes>
      </main>
    </>
  )
}
