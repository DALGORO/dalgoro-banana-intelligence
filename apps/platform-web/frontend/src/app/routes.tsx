import { lazy, Suspense, type ReactElement } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import AppShell from '../components/AppShell';
import Login from '../pages/Login';
import Companies from '../pages/Companies';
import CompanyDetailWithDbi from '../pages/CompanyDetailWithDbi';
import DbiDensityPage from '../pages/DbiDensityPage';
import DbiPilotPage from '../pages/DbiPilotPage';
import PaymentPage from '../pages/PaymentPage';
import Signup from '../pages/Signup';
import AdminPage from '../pages/AdminPage';

const FarmMapTimeline = lazy(() => import('../pages/FarmMapTimeline'));
const SamplingFieldPage = lazy(() => import('../pages/SamplingFieldPage'));
const InspectionFieldPage = lazy(() => import('../pages/InspectionFieldPage'));

function Protected({ element }: { element: ReactElement }) {
  return localStorage.getItem('token') ? element : <Navigate to="/login" replace />;
}

export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  { path: '/signup', element: <Signup /> },
  { path: '/admin', element: <Protected element={<AdminPage />} /> },
  {
    path: '/',
    element: <Protected element={<AppShell />} />,
    children: [
      { index: true, element: <Navigate to="companies" replace /> },
      { path: 'companies', element: <Companies /> },
      { path: 'companies/:id', element: <CompanyDetailWithDbi /> },
      { path: 'companies/:id/agricultura', element: <Protected element={<DbiPilotPage />} /> },
      { path: 'companies/:id/agricultura/densidad', element: <Protected element={<DbiDensityPage />} /> },
      { path: 'pay', element: <PaymentPage /> },
      {
        path: 'fincas/:fincaId/mapa',
        element: (
          <Protected
            element={(
              <Suspense fallback={<div className="card">Cargando visor cartográfico…</div>}>
                <FarmMapTimeline />
              </Suspense>
            )}
          />
        ),
      },
      {
        path: 'dbi/organizations/:organizationRef/farms/:farmId/plots/:plotId/sampling/:planId',
        element: (
          <Protected
            element={(
              <Suspense fallback={<div className="card">Cargando PWA de muestreo…</div>}>
                <SamplingFieldPage />
              </Suspense>
            )}
          />
        ),
      },
      {
        path: 'dbi/organizations/:organizationRef/farms/:farmId/plots/:plotId/inspection/new',
        element: (
          <Protected
            element={(
              <Suspense fallback={<div className="card">Cargando captura INSPECT…</div>}>
                <InspectionFieldPage />
              </Suspense>
            )}
          />
        ),
      },
    ],
  },
]);
