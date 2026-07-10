import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/features/auth/store/authStore";
import { cn } from "@/shared/lib/utils";

const navItems = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/runs", label: "Runs" },
  { to: "/projects/new", label: "New Project" },
];

export function Layout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Top navigation bar */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-8">
            {/* Logo */}
            <NavLink to="/dashboard" className="flex items-center gap-2">
              <span className="text-xl font-bold text-brand-600">⚡ ForgeAI</span>
            </NavLink>

            {/* Nav links */}
            <nav className="hidden md:flex gap-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      "px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                      isActive
                        ? "bg-brand-50 text-brand-700"
                        : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>

          {/* User menu */}
          <div className="flex items-center gap-3">
            <span className="hidden sm:block text-sm text-gray-600 truncate max-w-[200px]">
              {user?.email}
            </span>
            <button
              onClick={handleLogout}
              className="text-sm text-gray-500 hover:text-gray-900 transition-colors px-3 py-1.5 rounded-lg hover:bg-gray-100"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>
    </div>
  );
}
