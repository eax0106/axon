import type { components } from "@axon/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./api";

type S = components["schemas"];
export type Employee = S["app__employees__router__EmployeeOut"];
export type Script = S["ScriptBundle"];
export type Section = S["Section"];
export type Settings = S["EmployeeSettings"];
export type Voice = S["VoiceOut"];
export type Version = S["VersionOut"];
export type Channel = S["Channel"];
export type Language = "te" | "en" | "hi";

export const LANGUAGES: Record<Language, string> = { te: "Telugu", en: "English", hi: "Hindi" };
export const CHANNELS: Record<Channel, { label: string; blurb: string }> = {
  instant: { label: "Instant", blurb: "Calls every new lead from your website, ads or sheet within seconds." },
  bulk: { label: "Bulk", blurb: "Works through a list you upload, at the hours and pace you set." },
  inbound: { label: "Inbound", blurb: "Answers your business number, day and night." },
};

const path = (id: string) => ({ params: { path: { employee_id: id } } });

export const useEmployees = () =>
  useQuery({ queryKey: ["employees"], queryFn: () => unwrap(api.GET("/employees")) });

export const useEmployee = (id: string) =>
  useQuery({ queryKey: ["employee", id], queryFn: () => unwrap(api.GET("/employees/{employee_id}", path(id))) });

export const useVoices = () =>
  useQuery({ queryKey: ["voices"], queryFn: () => unwrap(api.GET("/voices")), staleTime: 10 * 60_000 });

export const useVersions = (id: string) =>
  useQuery({
    queryKey: ["employee", id, "versions"],
    queryFn: () => unwrap(api.GET("/employees/{employee_id}/versions", path(id))),
  });

type Path = ReturnType<typeof path>;
/** A write: the request, and optionally what the employee will look like, shown before the API answers. */
type Write = { run: (p: Path) => Promise<Employee>; preview?: (e: Employee) => Employee };

/** Every write that answers with the employee: the cache takes the server's copy as truth, and a
 *  write with a preview updates the screen at once and rolls back if the API refuses. */
export function useEmployeeWrite(id: string) {
  const qc = useQueryClient();
  const key = ["employee", id];
  return useMutation({
    mutationFn: (write: Write) => write.run(path(id)),
    onMutate: (write) => {
      const before = qc.getQueryData<Employee>(key);
      if (before && write.preview) qc.setQueryData(key, write.preview(before));
      return { before };
    },
    onError: (_e, _w, ctx) => ctx?.before && qc.setQueryData(key, ctx.before),
    onSuccess: (employee) => {
      qc.setQueryData(key, employee);
      void qc.invalidateQueries({ queryKey: ["employees"] });
      void qc.invalidateQueries({ queryKey: [...key, "versions"] });
    },
  });
}

const call = (run: Write["run"]): Write => ({ run });

/** The writes, named once so screens read like the owner's intent. */
export const writes = {
  script: (body: Script) => call((p) => unwrap(api.PUT("/employees/{employee_id}/script", { ...p, body }))),
  settings: (body: Settings): Write => ({
    run: (p) => unwrap(api.PUT("/employees/{employee_id}/settings", { ...p, body })),
    preview: (e) => ({ ...e, settings: body }),
  }),
  update: (body: S["EmployeeUpdate"]) => call((p) => unwrap(api.PATCH("/employees/{employee_id}", { ...p, body }))),
  publish: () => call((p) => unwrap(api.POST("/employees/{employee_id}/publish", p))),
  discard: () => call((p) => unwrap(api.POST("/employees/{employee_id}/revert", p))),
  activate: () => call((p) => unwrap(api.POST("/employees/{employee_id}/activate", p))),
  pause: () => call((p) => unwrap(api.POST("/employees/{employee_id}/deactivate", p))),
  reset: () => call((p) => unwrap(api.POST("/employees/{employee_id}/reset", p))),
  restore: (version: number) =>
    call((p) =>
      unwrap(api.POST("/employees/{employee_id}/versions/{version}/restore", { params: { path: { ...p.params.path, version } } })),
    ),
  switchChannel: (channel: Channel) =>
    call(async (p) => {
      const moved = await unwrap<{ employee: Employee }>(api.POST("/employees/{employee_id}/switch-mode", { ...p, body: { channel } }));
      return moved.employee;
    }),
};
