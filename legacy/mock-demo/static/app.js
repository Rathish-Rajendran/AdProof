"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = { scenarios: [], selected: null, submission: null, audit: null, running: false, timer: null, seenEvents: 0, selectedMessage: 0, messages: [], report: null };
  const stages = {
    RECEIVED: "Request received", VALIDATING: "Validate campaign",
    INSPECTING_ORIGINAL: "Inspect original creative", VERIFYING_ORIGINAL: "Verify original claims",
    REPAIRING_COPY: "Repair campaign copy", INSPECTING_REPAIRED: "Inspect repaired candidate",
    VERIFYING_REPAIRED: "Independently re-verify repair", COMPLETED: "Audit complete",
    PARTIAL: "Audit completed with recovery",
  };
  const pretty = (value) => String(value || "").replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (s) => s.toUpperCase());
  const stringify = (value) => JSON.stringify(value, null, 2);
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  };
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const asArray = (value) => Array.isArray(value) ? value : [];

  async function api(url, options) {
    const response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
      cache: "no-store",
    });
    let data;
    try { data = await response.json(); } catch { throw new Error("The local server returned an unreadable response."); }
    if (!response.ok) {
      const details = data?.error?.fields;
      const message = data?.error?.message || "The request could not be completed.";
      throw new Error(details ? message + " " + (typeof details === "string" ? details : stringify(details)) : message);
    }
    return data;
  }

  function showError(message) {
    $("error-banner").textContent = message;
    $("error-banner").hidden = !message;
  }

  function setRunning(running) {
    state.running = running;
    $("run-button").disabled = running || !state.selected;
    $("scenario-select").disabled = running;
    for (const id of ["ad-copy", "landing-url", "platform", "jurisdiction"]) $(id).disabled = running;
    $("replay-button").disabled = running || !state.submission;
    $("run-label").textContent = running ? "Audit in progress…" : "Run campaign audit";
    $("run-icon").textContent = running ? "◌" : "▶";
    $("run-icon").classList.toggle("spin", running);
  }

  function selectScenario(id) {
    state.selected = state.scenarios.find((scenario) => scenario.id === id) || state.scenarios[0];
    if (!state.selected) return;
    const scenario = state.selected;
    const campaign = scenario.campaign;
    $("scenario-select").value = scenario.id;
    $("scenario-description").textContent = scenario.description;
    $("scenario-expected").textContent = "EXPECT " + (typeof scenario.expected === "string" ? scenario.expected.replaceAll("_", " ") : "MOCK RESULT");
    $("ad-copy").value = campaign.creative.ad_copy;
    $("landing-url").value = campaign.landing_page_url;
    $("platform").value = campaign.campaign.platform;
    $("jurisdiction").value = campaign.campaign.jurisdiction;
    $("creative-preview").src = campaign.creative.image_url;
    $("creative-preview").alt = scenario.name + " — fictional mock advertisement";
    showError("");
    setRunning(false);
  }

  function buildSubmission() {
    const campaign = clone(state.selected.campaign);
    const requestId = "demo-" + (globalThis.crypto?.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(16).slice(2));
    campaign.request_id = requestId;
    campaign.creative.ad_copy = $("ad-copy").value.trim();
    campaign.landing_page_url = $("landing-url").value.trim();
    campaign.campaign.platform = $("platform").value;
    campaign.campaign.jurisdiction = $("jurisdiction").value;
    return { scenario_id: state.selected.id, request_id: requestId, campaign };
  }

  function resetAudit() {
    clearTimeout(state.timer);
    state.audit = null;
    state.report = null;
    state.seenEvents = 0;
    state.selectedMessage = 0;
    state.messages = [];
    $("timeline").replaceChildren();
    $("message-list").replaceChildren(node("p", "inspector-empty", "Waiting for the first agent message…"));
    $("message-json").textContent = stringify({ execution_mode: "MOCK", status: "starting_audit" });
    $("report-json").textContent = "Audit running. The canonical report appears when all stages finish.";
    $("copy-report").disabled = true;
    $("result-content").hidden = true;
    $("result-empty").hidden = false;
    $("result-empty").querySelector("h3").textContent = "Your campaign is being reviewed";
    $("result-empty").querySelector("p").textContent = "Follow the timeline as each specialist returns a result.";
    $("audit-id").textContent = "Submitting…";
    $("message-count").textContent = "0";
    $("elapsed").textContent = "0.0s";
    $("activity-count").textContent = "0 events";
    $("workflow-status").className = "status-pill running";
    $("workflow-status").textContent = "Starting";
    document.querySelectorAll("[data-agent]").forEach((agent) => {
      agent.className = "agent-item";
      agent.querySelector(".agent-state").textContent = "Ready";
    });
  }

  async function runAudit(event) {
    event.preventDefault();
    if (state.running || !state.selected) return;
    showError("");
    state.submission = buildSubmission();
    resetAudit();
    setRunning(true);
    try {
      const accepted = await api("/api/audits", { method: "POST", body: stringify(state.submission) });
      state.audit = accepted.audit_id;
      await poll(accepted.status_url || "/api/audits/" + encodeURIComponent(accepted.audit_id));
    } catch (error) {
      showError(error.message);
      setRunning(false);
      $("workflow-status").className = "status-pill failed";
      $("workflow-status").textContent = "Request failed";
      $("workflow-footer-label").textContent = "Review the error and try a new request.";
    }
  }

  async function poll(url) {
    const snapshot = await api(url);
    renderSnapshot(snapshot);
    if (snapshot.workflow_status === "RUNNING") {
      state.timer = setTimeout(() => {
        poll(url).catch((error) => {
          showError("The local connection was interrupted. " + error.message + " Use “Replay request” to recover the existing audit without starting a duplicate.");
          setRunning(false);
          $("workflow-status").className = "status-pill failed";
          $("workflow-status").textContent = "Connection interrupted";
        });
      }, 350);
    } else {
      setRunning(false);
    }
  }

  function renderSnapshot(snapshot) {
    state.audit = snapshot.audit_id;
    $("audit-id").textContent = snapshot.audit_id;
    $("audit-id").title = snapshot.audit_id;
    $("elapsed").textContent = (Number(snapshot.elapsed_ms || snapshot.report?.timings_ms?.total || 0) / 1000).toFixed(1) + "s";
    $("workflow-status").className = "status-pill " + String(snapshot.workflow_status || "RUNNING").toLowerCase();
    $("workflow-status").textContent = snapshot.workflow_status === "RUNNING" ? "Running" : pretty(snapshot.workflow_status);
    const events = asArray(snapshot.events);
    $("activity-count").textContent = events.length + " events";
    renderEvents(events);
    renderAgents(events, snapshot.workflow_status, asArray(snapshot.report?.errors));
    renderMessages(asArray(snapshot.messages || snapshot.report?.messages));
    if (snapshot.report) renderReport(snapshot.report);
    $("workflow-footer-label").textContent = snapshot.workflow_status === "RUNNING"
      ? "Routing structured messages between mock agents."
      : snapshot.workflow_status === "PARTIAL"
        ? "Recovery preserved the last verified decision."
        : "Workflow complete. Inspect every handoff below.";
  }

  function renderEvents(events) {
    const timeline = $("timeline");
    if (events.length < state.seenEvents) {
      timeline.replaceChildren();
      state.seenEvents = 0;
    }
    const nearBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 70;
    for (const event of events.slice(state.seenEvents)) {
      const isError = ["error", "retry"].includes(event.type);
      const isSuccess = ["stage_completed", "complete", "decision", "message_received"].includes(event.type);
      const row = node("div", "timeline-event " + (isError ? "event-error" : isSuccess ? "event-success" : ""));
      row.append(node("span", "event-dot", isError ? "!" : isSuccess ? "✓" : "·"));
      const line = node("div", "event-line");
      let title = event.type === "stage_started" ? stages[event.stage] || pretty(event.stage) : pretty(event.type);
      if (event.type === "retry") title = "Retry with bounded recovery";
      if (event.type === "decision") title = event.message;
      if (event.type === "complete") title = "Audit report assembled";
      line.append(node("strong", "event-title", title), node("span", "event-time", "+" + (Number(event.elapsed_ms || 0) / 1000).toFixed(2) + "s"));
      row.append(line);
      if (event.type !== "decision") row.append(node("p", "event-detail", event.message));
      if (event.agent) row.append(node("span", "event-agent", event.agent + (event.phase ? " · " + event.phase : "")));
      timeline.append(row);
    }
    state.seenEvents = events.length;
    if (nearBottom) timeline.scrollTop = timeline.scrollHeight;
  }

  function renderAgents(events, workflowStatus, errors) {
    document.querySelectorAll("[data-agent]").forEach((element) => {
      const role = element.dataset.agent;
      const activity = events.filter((event) => String(event.agent || "").toLowerCase() === role);
      let status = activity.length ? "done" : "";
      let label = activity.length ? "Returned" : "Ready";
      const latest = activity.at(-1);
      if (workflowStatus === "RUNNING" && ["stage_started", "message_sent"].includes(latest?.type)) { status = "working"; label = "Working"; }
      if (workflowStatus === "RUNNING" && latest?.type === "retry") { status = "working"; label = "Retrying"; }
      if (latest?.type === "error") { status = "error"; label = "Recovering"; }
      if (role === "orchestrator" && workflowStatus === "RUNNING") { status = "working"; label = "Coordinating"; }
      if (role === "orchestrator" && workflowStatus !== "RUNNING") { status = workflowStatus === "PARTIAL" ? "error" : "done"; label = workflowStatus === "PARTIAL" ? "Recovered" : "Complete"; }
      const failedStage = errors.find((error) => {
        const stage = String(error.stage || "");
        return (role === "verifier" && stage.startsWith("VERIFYING"))
          || (role === "inspector" && stage.startsWith("INSPECTING"))
          || (role === "remediator" && stage === "REPAIRING_COPY");
      });
      if (failedStage) { status = "error"; label = failedStage.code === "SPECIALIST_TIMEOUT" ? "Timed out" : "Failed"; }
      element.className = "agent-item " + status;
      element.querySelector(".agent-state").textContent = label;
    });
  }

  function renderMessages(messages) {
    $("message-count").textContent = String(messages.length);
    if (messages.length === state.messages.length) return;
    state.messages = messages;
    const list = $("message-list");
    list.replaceChildren();
    if (!messages.length) { list.append(node("p", "inspector-empty", "Waiting for the first agent message…")); return; }
    messages.forEach((message, index) => {
      const button = node("button", "message-row" + (index === state.selectedMessage ? " active" : ""));
      button.type = "button";
      button.append(node("strong", "", pretty(message.sender || "orchestrator") + " → " + pretty(message.recipient || "specialist")));
      button.append(node("span", "", (message.operation || message.message_type || message.type || "MESSAGE") + " · " + (message.phase || "AUDIT") + " · attempt " + (message.attempt || 1) + " · " + (message.direction || "handoff")));
      button.addEventListener("click", () => selectMessage(index));
      list.append(button);
    });
    selectMessage(Math.min(state.selectedMessage, messages.length - 1));
  }

  function selectMessage(index) {
    state.selectedMessage = index;
    const message = state.messages[index];
    if (!message) return;
    $("message-json").textContent = stringify(message);
    $("message-detail-label").textContent = (message.operation || "MESSAGE") + " · " + (message.direction || "ENVELOPE");
    [...$("message-list").children].forEach((element, i) => element.classList.toggle("active", i === index));
  }

  function setDecision(id, decision) {
    const element = $(id);
    element.textContent = decision ? decision.replaceAll("_", " ") : "NOT VERIFIED";
    element.className = "decision-badge " + String(decision || "").toLowerCase().replaceAll("_", "-");
  }

  function safeLink(url, label) {
    try {
      const parsed = new URL(url, location.origin);
      if (!["http:", "https:"].includes(parsed.protocol)) return node("span", "", label);
      const link = node("a", "", label);
      link.href = parsed.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      return link;
    } catch { return node("span", "", label); }
  }

  function renderReport(report) {
    state.report = report;
    $("result-empty").hidden = true;
    $("result-content").hidden = false;
    setDecision("initial-decision", report.initial_decision);
    setDecision("final-decision", report.final_decision);
    $("decision-route-label").textContent = report.repair
      ? report.repaired_verification ? "Copy repair independently re-verified" : "Repair remains unverified"
      : "Original candidate retained";
    const descriptions = {
      PASS: "This candidate passed the bundled mock rules. No publication or platform approval is implied.",
      BLOCK: "Verified critical issues remain. The campaign must not pass this demo gate.",
      FIX_REQUIRED: "The candidate still has issues requiring a fix before it can pass.",
      HUMAN_REVIEW: "A required verification could not finish. Ask a person to review the campaign.",
    };
    $("final-description").textContent = descriptions[report.final_decision] || "Inspect the evidence and workflow errors before proceeding.";
    const issues = asArray(report.issues);
    const claims = asArray(report.claims);
    const revisedIssues = asArray(report.repaired_verification?.issues);
    $("findings-context").textContent = report.repaired_verification
      ? "Original findings · revised candidate has " + revisedIssues.length + " remaining " + (revisedIssues.length === 1 ? "issue" : "issues")
      : report.repair ? "Original findings · repair not verified" : "Original candidate findings";
    $("issue-count").textContent = String(issues.length);
    $("claim-count").textContent = String(claims.length);
    $("issues-list").replaceChildren();
    $("claims-list").replaceChildren();
    if (!issues.length) $("issues-list").append(node("p", "finding-empty", report.initial_decision === null
      ? "Original verification did not finish. No findings are available."
      : "No issues were matched by the bundled demo rules."));
    issues.forEach((issue) => {
      const finding = node("article", "finding");
      const top = node("div", "finding-top");
      top.append(node("h3", "finding-category", pretty(issue.category)), node("span", "severity-tag " + String(issue.severity || "").toLowerCase(), issue.severity || "ISSUE"));
      finding.append(top, node("p", "", issue.explanation));
      const source = node("div", "finding-source", pretty(issue.source) + " · ");
      const policy = issue.policy;
      if (policy?.url) source.append(safeLink(policy.url, policy.title || policy.authority || "Policy fixture"));
      else source.append(node("span", "", issue.policy_source || "Demo policy"));
      finding.append(source);
      if (issue.suggested_fix) finding.append(node("p", "evidence-excerpt", issue.suggested_fix));
      $("issues-list").append(finding);
    });
    if (!claims.length) $("claims-list").append(node("p", "finding-empty", "No verified claims are available for this run."));
    claims.forEach((claim) => {
      const finding = node("article", "finding");
      const top = node("div", "finding-top");
      top.append(node("h3", "finding-category", claim.claim || claim.text || claim.claim_text || "Extracted claim"), node("span", "severity-tag " + String(claim.status || "").toLowerCase(), claim.status || "PENDING"));
      finding.append(top, node("span", "finding-source", pretty(claim.source) + " · " + pretty(claim.claim_type)));
      asArray(claim.evidence).forEach((evidence) => {
        if (evidence.excerpt) finding.append(node("p", "evidence-excerpt", evidence.excerpt));
        if (evidence.source_url) {
          const source = node("div", "finding-source");
          source.append(safeLink(evidence.source_url, evidence.source_type === "LANDING_PAGE" ? "View landing-page fixture ↗" : "View evidence ↗"));
          finding.append(source);
        }
      });
      $("claims-list").append(finding);
    });
    const repairedCopy = report.repair?.repaired_copy;
    $("repair-section").hidden = !repairedCopy;
    $("repaired-copy").textContent = repairedCopy || "";
    const reasons = [...asArray(report.human_review_reasons), ...asArray(report.errors).map((error) => (error.code || "WORKFLOW_ERROR") + ": " + (error.message || "A workflow stage failed."))];
    $("review-section").hidden = !reasons.length;
    $("review-reasons").replaceChildren(...reasons.map((reason) => node("li", "", typeof reason === "string" ? reason : stringify(reason))));
    $("download-report").href = "/api/audits/" + encodeURIComponent(report.audit_id) + "/report";
    $("download-report").download = "adproof-" + report.audit_id + ".json";
    $("report-json").textContent = stringify(report);
    $("copy-report").disabled = false;
  }

  async function replayRequest() {
    if (!state.submission || state.running) return;
    showError("");
    $("replay-button").disabled = true;
    $("replay-button").textContent = "Checking…";
    try {
      const accepted = await api("/api/audits", { method: "POST", body: stringify(state.submission) });
      if (accepted.audit_id !== state.audit) resetAudit();
      const url = accepted.status_url || "/api/audits/" + encodeURIComponent(accepted.audit_id);
      const snapshot = await api(url);
      renderSnapshot(snapshot);
      $("workflow-footer-label").textContent = accepted.replayed
        ? "Idempotent replay: same audit. No duplicate run."
        : "Request recovered as " + accepted.audit_id + ".";
      if (snapshot.workflow_status === "RUNNING") {
        setRunning(true);
        await poll(url);
      } else setRunning(false);
    } catch (error) { showError(error.message); }
    finally {
      $("replay-button").disabled = state.running;
      $("replay-button").textContent = "Replay request ↻";
    }
  }

  function configureTabs(selector, attribute, views) {
    document.querySelectorAll(selector).forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(selector).forEach((tab) => {
          const selected = tab === button;
          tab.classList.toggle("active", selected);
          tab.setAttribute("aria-selected", String(selected));
        });
        Object.entries(views).forEach(([name, id]) => { $(id).hidden = name !== button.dataset[attribute]; });
      });
    });
  }

  $("audit-form").addEventListener("submit", runAudit);
  $("scenario-select").addEventListener("change", (event) => selectScenario(event.target.value));
  $("replay-button").addEventListener("click", replayRequest);
  $("copy-report").addEventListener("click", async () => {
    if (!state.report) return;
    try {
      await navigator.clipboard.writeText(stringify(state.report));
      $("copy-report").textContent = "Copied ✓";
      setTimeout(() => { $("copy-report").textContent = "Copy JSON"; }, 2000);
    } catch { showError("Clipboard access is unavailable. Download the report JSON instead."); }
  });
  configureTabs("[data-result-tab]", "resultTab", { issues: "issues-list", claims: "claims-list" });
  configureTabs("[data-inspector-tab]", "inspectorTab", { messages: "messages-view", json: "json-view" });
  setRunning(false);

  async function initialize() {
    const results = await Promise.allSettled([api("/api/health"), api("/api/scenarios")]);
    if (results[0].status === "fulfilled") {
      $("health-dot").className = "status-dot online";
      $("health-label").textContent = "Local server connected";
    } else {
      $("health-dot").className = "status-dot offline";
      $("health-label").textContent = "Local server unavailable";
    }
    if (results[1].status === "fulfilled") {
      state.scenarios = asArray(results[1].value.scenarios);
      $("scenario-select").replaceChildren(...state.scenarios.map((scenario) => {
        const option = node("option", "", scenario.name);
        option.value = scenario.id;
        return option;
      }));
      if (!state.scenarios.length) throw new Error("The server returned no demo scenarios.");
      selectScenario(state.scenarios[0].id);
    } else {
      throw results[1].reason;
    }
  }
  initialize().catch((error) => {
    showError("Could not load the demo. Start the local AdProof server and refresh this page. " + error.message);
    $("scenario-description").textContent = "Unable to load fixtures.";
    $("scenario-select").disabled = true;
  });
})();
