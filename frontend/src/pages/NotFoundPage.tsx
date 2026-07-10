import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="text-center">
        <p className="text-6xl font-bold text-brand-600 mb-4">404</p>
        <h1 className="text-2xl font-semibold text-gray-800 mb-2">Page Not Found</h1>
        <p className="text-gray-500 text-sm mb-8">
          The page you are looking for does not exist.
        </p>
        <Link
          to="/dashboard"
          className="inline-flex items-center px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
        >
          Return to Dashboard
        </Link>
      </div>
    </div>
  );
}
