import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "@/shared/components/Layout";
import { ProtectedRoute } from "@/shared/components/ProtectedRoute";
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { NewProjectPage } from "@/pages/NewProjectPage";
import { ProjectDetailPage } from "@/pages/ProjectDetailPage";
import { RunDetailPage } from "@/pages/RunDetailPage";
import { RunHistoryPage } from "@/pages/RunHistoryPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Navigate to="/dashboard" replace />,
  },
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/register",
    element: <RegisterPage />,
  },
  {
    element: (
      <ProtectedRoute>
        <Layout />
      </ProtectedRoute>
    ),
    children: [
      {
        path: "/dashboard",
        element: <DashboardPage />,
      },
      {
        path: "/projects/new",
        element: <NewProjectPage />,
      },
      {
        path: "/projects/:id",
        element: <ProjectDetailPage />,
      },
      {
        path: "/runs",
        element: <RunHistoryPage />,
      },
      {
        path: "/runs/:runId",
        element: <RunDetailPage />,
      },
    ],
  },
  {
    path: "*",
    element: <NotFoundPage />,
  },
]);
