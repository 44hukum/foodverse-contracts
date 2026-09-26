import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, RequireAuth } from './auth/AuthContext';
import { Layout } from './components/Layout';
import { ContractDetailPage } from './pages/ContractDetailPage';
import { ContractListPage } from './pages/ContractListPage';
import { CreateContractPage } from './pages/CreateContractPage';
import { LoginPage } from './pages/LoginPage';

/**
 * Admin routes only. The signer-facing `/sign/:token` page is a separate issue
 * and lives under `src/sign/`, which this app does not touch.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/contracts" element={<ContractListPage />} />
        <Route path="/contracts/new" element={<CreateContractPage />} />
        <Route path="/contracts/:contractId" element={<ContractDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/contracts" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
