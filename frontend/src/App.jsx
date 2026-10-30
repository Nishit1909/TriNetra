import { Routes, Route } from 'react-router-dom';
import Shell from './components/Shell';
import Dashboard from './pages/Dashboard';
import Network from './pages/Network';
import Placeholder from './pages/Placeholder';

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/network" element={<Network />} />
        <Route path="/people" element={<Placeholder name="People" />} />
        <Route path="/cases" element={<Placeholder name="Cases" />} />
        <Route path="/communities" element={<Placeholder name="Communities" />} />
        <Route path="/predictions" element={<Placeholder name="Predictions" />} />
        <Route path="/ingestion" element={<Placeholder name="Ingestion" />} />
      </Routes>
    </Shell>
  );
}
