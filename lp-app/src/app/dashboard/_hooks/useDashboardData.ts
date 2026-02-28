"use client";

import { useEffect, useState, useCallback } from "react";
import type { DashboardData } from "../_types/dashboard";

export interface ScheduleEditTarget {
  schedulerName: string;
  scriptLabel: string;
  currentCron: string;
}

export interface UseDashboardDataReturn {
  data: DashboardData | null;
  autoRefresh: boolean;
  setAutoRefresh: (v: boolean) => void;
  executing: string | null;
  approving: string | null;
  togglingScheduler: string | null;
  globalToggling: boolean;
  scheduleEditTarget: ScheduleEditTarget | null;
  setScheduleEditTarget: (v: ScheduleEditTarget | null) => void;
  scheduleEditCron: string;
  setScheduleEditCron: (v: string) => void;
  scheduleEditSaving: boolean;
  fetchData: (nocache?: boolean) => Promise<void>;
  handleApprove: (ideaId: string, action: "approve" | "reject") => Promise<void>;
  handleExecute: (scriptId: string) => Promise<void>;
  handleSchedulerToggle: (schedulerName: string, currentState: string) => Promise<void>;
  handleGlobalToggle: (action: "pause_all" | "resume_all") => Promise<void>;
  handleScheduleSave: () => Promise<void>;
}

export function useDashboardData(): UseDashboardDataReturn {
  const [data, setData] = useState<DashboardData | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [approving, setApproving] = useState<string | null>(null);
  const [executing, setExecuting] = useState<string | null>(null);
  const [togglingScheduler, setTogglingScheduler] = useState<string | null>(null);
  const [globalToggling, setGlobalToggling] = useState(false);
  const [scheduleEditTarget, setScheduleEditTarget] = useState<ScheduleEditTarget | null>(null);
  const [scheduleEditCron, setScheduleEditCron] = useState("");
  const [scheduleEditSaving, setScheduleEditSaving] = useState(false);

  const fetchData = useCallback(async (nocache = false) => {
    try {
      const url = nocache ? "/api/dashboard?nocache=1" : "/api/dashboard";
      const res = await fetch(url);
      if (res.ok) setData(await res.json());
    } catch {
      /* network error */
    }
  }, []);

  useEffect(() => {
    fetchData();
    if (!autoRefresh) return;
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData, autoRefresh]);

  const handleApprove = async (ideaId: string, action: "approve" | "reject") => {
    setApproving(ideaId);
    try {
      await fetch("/api/slack/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea_id: ideaId, action }),
      });
      await fetchData(true);
    } finally {
      setApproving(null);
    }
  };

  const handleExecute = async (scriptId: string) => {
    setExecuting(scriptId);
    try {
      const res = await fetch("/api/dashboard/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scriptId }),
      });
      if (!res.ok) console.error("Execute failed:", await res.json());
      await fetchData(true);
    } catch (err) {
      console.error("Execute error:", err);
    } finally {
      setExecuting(null);
    }
  };

  const handleSchedulerToggle = async (schedulerName: string, currentState: string) => {
    setTogglingScheduler(schedulerName);
    try {
      const action = currentState === "ENABLED" ? "pause" : "resume";
      await fetch("/api/dashboard/scheduler", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scheduler: schedulerName, action }),
      });
      await fetchData(true);
    } catch (err) {
      console.error("Scheduler toggle error:", err);
    } finally {
      setTogglingScheduler(null);
    }
  };

  const handleGlobalToggle = async (action: "pause_all" | "resume_all") => {
    setGlobalToggling(true);
    try {
      await fetch("/api/dashboard/scheduler", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      await fetchData(true);
    } catch (err) {
      console.error("Global toggle error:", err);
    } finally {
      setGlobalToggling(false);
    }
  };

  const handleScheduleSave = async () => {
    if (!scheduleEditTarget || !scheduleEditCron.trim()) return;
    setScheduleEditSaving(true);
    try {
      const res = await fetch("/api/dashboard/scheduler", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jobId: scheduleEditTarget.schedulerName,
          schedule: scheduleEditCron.trim(),
        }),
      });
      if (res.ok) {
        setScheduleEditTarget(null);
        await fetchData(true);
      } else {
        const err = await res.json();
        alert(err.error || "スケジュール更新に失敗しました");
      }
    } catch (err) {
      console.error("Schedule edit error:", err);
      alert("スケジュール更新に失敗しました");
    } finally {
      setScheduleEditSaving(false);
    }
  };

  return {
    data,
    autoRefresh,
    setAutoRefresh,
    executing,
    approving,
    togglingScheduler,
    globalToggling,
    scheduleEditTarget,
    setScheduleEditTarget,
    scheduleEditCron,
    setScheduleEditCron,
    scheduleEditSaving,
    fetchData,
    handleApprove,
    handleExecute,
    handleSchedulerToggle,
    handleGlobalToggle,
    handleScheduleSave,
  };
}
