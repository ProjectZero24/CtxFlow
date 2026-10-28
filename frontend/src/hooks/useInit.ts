import { useEffect, useRef } from "react";
import { useAppState, useDispatch } from "../store/AppContext";
import { api } from "../api";

export function useInit() {
  const state = useAppState();
  const dispatch = useDispatch();
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    // Load health
    api.health()
      .then((h) => dispatch({ type: "SET_HEALTH", payload: h }))
      .catch(() => {});

    // Load projects
    api.projects.list()
      .then((projects) => dispatch({ type: "SET_PROJECTS", payload: projects }))
      .catch(() => {});

    // Poll health every 30s
    const interval = setInterval(() => {
      api.health()
        .then((h) => dispatch({ type: "SET_HEALTH", payload: h }))
        .catch(() => {});
    }, 30_000);

    return () => clearInterval(interval);
  }, [dispatch]);

  // Reload runs when project changes
  useEffect(() => {
    api.runs.list(state.currentProjectId)
      .then((runs) => dispatch({ type: "SET_RUNS", payload: runs }))
      .catch(() => {});
  }, [state.currentProjectId, dispatch]);
}
