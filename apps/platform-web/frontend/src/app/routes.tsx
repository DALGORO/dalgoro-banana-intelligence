import { createBrowserRouter, Navigate } from 'react-router-dom';
import AppShell from '../components/AppShell';
import Login from '../pages/Login';
import Dashboard from '../pages/Dashboard';
import Companies from '../pages/Companies';
import CompanyDetail from '../pages/CompanyDetail';
import Documents from '../pages/Documents';
import DocumentViewer from '../pages/DocumentViewer';
import DocumentForm from "../pages/DocumentForm";
import TemplatesCatalog from '../pages/TemplatesCatalog';
import PaymentPage from '../pages/PaymentPage';
import Signup from '../pages/Signup';
import IncidentAssistant from '../pages/IncidentAssistant';
import IPERCTab from '@/pages/IPERCTab';
import AdminPage from '../pages/AdminPage';



const enableDocs = import.meta.env.VITE_ENABLE_DOCS === "1";

function Protected({ element }: { element: JSX.Element }) {
  return localStorage.getItem('token') ? element : <Navigate to="/login" replace />;
}

export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  { path: '/signup', element: <Signup /> },
  { path: '/admin', element: <Protected element={<AdminPage />} /> },  // ✅ Redirige y evita el error
  {
    path: '/',
    element: <Protected element={<AppShell />} />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'companies', element: <Companies /> },
      { path: 'companies/:id', element: <CompanyDetail /> },
      { path: 'pay', element: <PaymentPage /> },
      { path: 'companies/:id/iperc', element: <Protected element={<IPERCTab/>} /> },
      { path: 'companies/:id/investigacion-incidentes', element: <Protected element={<IncidentAssistant />} /> },

      // Rutas de documentos SOLO si el flag está activo
      ...(enableDocs ? [
        { path: 'companies/:id/documents', element: <Protected element={<Documents />} /> },
        {
          path: 'companies/:id/documents/new/:code',
          element: <Protected element={<DocumentForm />} />,
        },
        { path: 'documents/:docId', element: <DocumentViewer /> },
        { path: 'documents/new', element: <Protected element={<TemplatesCatalog />} /> },
      ] : []),
    ],
  },
  ]);
