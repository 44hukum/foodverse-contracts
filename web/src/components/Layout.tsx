import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

export function Layout() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();

  function onLogout(): void {
    logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className="app">
      <header className="app-header">
        <Link to="/contracts" className="brand">
          Foodverse Contracts
        </Link>
        <nav aria-label="Main">
          <NavLink to="/contracts" end>
            Contracts
          </NavLink>
          <NavLink to="/contracts/new">New contract</NavLink>
        </nav>
        <div className="header-user">
          {session && <span className="muted">{session.admin.name}</span>}
          <button type="button" className="link-button" onClick={onLogout}>
            Log out
          </button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
