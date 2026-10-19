/** AR03 report types, from the generated OpenAPI types. */

import type { components, paths } from "@/api/types";

type S = components["schemas"];
export type AnalysisReport = S["AnalysisReportOut"];
export type ReportIssue = S["ReportIssue"];
export type BandBox = S["BandBox"];
export type Matrix = S["CorrelationMatrix"];
export type AnalysisReportQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/analysis/report"]["get"]["parameters"]["query"]
>;
/** The API always sends these seven bands, in this order (schema: band is a string). */
export type BandKey = "du" | "wa" | "wb" | "wc" | "wd" | "we" | "cf";
export type AssistantAnswer = S["AssistantAnswerOut"];
export type AssistantFollowup = S["AssistantFollowup"];
export type AssistantQuestions = S["AssistantQuestionsOut"];
export type AssistantQuestion = S["AssistantQuestion"];
export type AssistantSlot = S["AssistantSlot"];
