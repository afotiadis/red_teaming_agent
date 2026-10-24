# Chapter 5 — Conclusions, Limitations, and Future Work

## Introduction

The increasing integration of large language models with tools, private data, persistent memory, and external services has expanded both the capabilities and the attack surface of artificial-intelligence applications. Agentic AI systems can no longer be evaluated only as text-generation models. Their security also depends on instruction handling, authorization boundaries, retrieval behaviour, tool permissions, memory management, and the side effects that an agent can produce in its operating environment. These characteristics create a need for assessment methods that are adaptive enough to interact with complex AI behaviour, but controlled enough to produce reproducible and auditable security evidence.

This thesis addressed that need through the design and implementation of an automated red-teaming framework for agentic AI systems. The framework organizes an assessment as an iterative **Plan–Execute–Analyze–Adapt–Report** process. Specialized LLM agents perform tasks that benefit from strategic and semantic reasoning, while deterministic components validate plans, mediate interactions with the target, classify evidence, maintain campaign state, and construct the final report. Target profiles, dossiers, attack playbooks, coverage tracking, and experiential memory connect general red-teaming knowledge with the specific assets and security objectives of the system under evaluation.

This final chapter summarizes the conclusions that can be drawn from the work, explains its contribution to the field of AI red-teaming, identifies the principal limitations of the current implementation, and proposes directions through which the framework could evolve into a broader AI-security assessment platform.

## 5.1 Conclusions

The work presented in this thesis demonstrates the technical feasibility of combining agentic reasoning with deterministic security controls in a complete automated assessment lifecycle. The resulting framework does more than generate adversarial prompts. It establishes a process through which attacks are selected according to target-specific objectives, delivered through a controlled execution boundary, evaluated using normalized outcomes, and used to inform subsequent testing rounds.

A central conclusion of the project is that useful automation in AI red-teaming does not require every component to be autonomous. On the contrary, the most dependable architecture is obtained by assigning autonomy selectively. LLM agents are effective at generating context-sensitive attacks, varying an unsuccessful strategy, interpreting natural-language responses, and producing readable security explanations. They are less suitable for operations that require exactness, including target authentication, retry safety, evidence preservation, state transitions, and report completeness. The framework therefore treats the LLM as a reasoning component rather than as the trusted controller of the complete system.

The separation between reasoning and execution also addresses an important problem introduced by the use of LLMs inside security tools. A planning model may produce malformed structured output, request an unsupported operation, or describe actions that should not be performed. In the proposed architecture, such output does not directly reach the target. It must first pass through a deterministic runner that accepts only known operations and can replace an unusable plan with a bounded fallback. This does not eliminate all risks associated with model-generated attacks, but it establishes a clear control boundary around them.

Another conclusion is that meaningful AI red-teaming must be both taxonomy-aware and target-aware. A generic category such as information disclosure is useful for comparing campaigns, but it does not define what information matters in a particular application. A medical assistant, banking agent, and tool-enabled support system expose different assets and authorization boundaries. The use of target dossiers and objective-specific playbooks allows the same general methodology to be specialized without embedding all target assumptions in the orchestration logic.

The adaptive feedback loop represents a further improvement over one-shot prompt testing. Each round produces evidence that affects the next planning context. A blocked attack can cause a change in attack family, a deflection can cause a change in framing, a partial disclosure can be investigated further, and a confirmed finding can redirect effort toward an uncovered objective. The implemented adaptation remains bounded and heuristic, but it demonstrates how red-teaming can be organized as a campaign rather than as a collection of unrelated prompts.

Finally, the work shows the importance of separating security interpretation from security evidence. The Reporter can explain the significance of the results, but it cannot replace the original transcript. Payloads, target responses, transport information, retry decisions, and outcome classifications are assembled independently and checked for completeness before a report is archived. This approach improves auditability and makes it possible for a human reviewer to distinguish an actual observation from the model's interpretation of that observation.

Within the targets and experimental conditions considered in this thesis, the framework therefore establishes a viable proof of concept for controlled, adaptive, and evidence-aware AI red-teaming. The results should not be interpreted as proof that the system can discover every vulnerability or that it is superior to every existing red-teaming approach. Rather, they demonstrate that the proposed architectural pattern is implementable and provides a credible foundation for further research.

## 5.2 Contribution to the Field of AI Red-Teaming

The principal contribution of this thesis is not the introduction of a universally effective adversarial prompt or a new general-purpose attack algorithm. Its contribution is the design and realization of an integrated methodology for automating red-team campaigns against agentic AI applications. The framework brings together probabilistic reasoning, deterministic control, target-specific knowledge, adaptive feedback, and evidence-preserving reporting within a coherent lifecycle.

Python, CrewAI, retrieval-augmented generation, and the selected LLM services are enabling technologies rather than research contributions by themselves. The contribution lies in the manner in which these technologies are constrained and connected to support a security-assessment process.

### 5.2.1 Hybrid Agentic–Deterministic Architecture

The first contribution is an architectural pattern that separates strategic reasoning from external side effects. The Strategist, Response Analyzer, and Reporter are assigned tasks that benefit from linguistic and contextual reasoning. A deterministic layer controls plan validation, network execution, state management, classification, evidence assembly, and report validation.

This division is significant for AI red-teaming because the testing system is itself built around probabilistic AI components. If those components directly controlled all external operations, malformed output or hallucinated tool use could affect the target or corrupt the evidence. The hybrid architecture reduces this risk while preserving the flexibility that motivates the use of LLM agents in the first place.

### 5.2.2 Closed-Loop, Evidence-Informed Assessment

The second contribution is the organization of red-teaming as a closed feedback loop. Conventional prompt suites frequently evaluate each payload independently. In the proposed framework, results are converted into structured feedback and coverage information that becomes part of the next planning task.

This transforms attack generation from a static test list into an adaptive campaign. The framework can react differently to a refusal, a deflection, a partial disclosure, and a confirmed compromise. Although the present decision rules are relatively simple, the feedback-loop abstraction provides a foundation on which more advanced search and optimization methods can be studied.

### 5.2.3 Objective- and Coverage-Aware Testing

The third contribution is the connection between broad vulnerability categories and target-specific security objectives. The vulnerability taxonomy provides consistency, while dossiers identify the assets, roles, trust boundaries, and success indicators that matter for a particular target.

Coverage is consequently measured at both levels. Category coverage supports comparison across assessments, whereas objective coverage shows whether the campaign has addressed the application-specific risks it was configured to investigate. This does not prove the absence of untested vulnerabilities, but it provides a more meaningful indication of campaign progress than the number of prompts sent alone.

### 5.2.4 Reusable Target and Attack Abstractions

The framework introduces separate abstractions for target communication and campaign knowledge. Target profiles describe how requests are formed and authenticated. Dossiers describe what should be protected. Playbooks describe how relevant objectives may be tested. Execution adapters describe how a validated plan is delivered.

This separation reduces coupling between the assessment methodology and any single application. Supporting a new target still requires expert configuration, but it does not require reconstruction of the complete plan–execute–analyze lifecycle. The resulting artifact is therefore suitable for continued experimentation with different targets, attack families, and LLM providers.

### 5.2.5 Traceable Evidence and Controlled Reporting

The fifth contribution is an evidence-first reporting process. Exact execution records are retained independently of the Reporter agent, and completeness is checked before the final artifact is accepted. This reduces the possibility that an LLM-generated narrative will omit failed tests, invent target behaviour, or replace a long transcript with an unsupported summary.

This feature is especially important in security research, where the credibility of a finding depends on the connection between the claim and the underlying observation. The generated report remains partly interpretive, but the interpretation can be reviewed against the preserved evidence.

### 5.2.6 Foundation for Experimental Comparison

Normalized outcomes, objective coverage, campaign history, and benchmark-specific metrics provide a basis for future empirical studies. The framework can be used to compare static and adaptive attack generation, different planning models, alternative classifiers, distinct playbook collections, and campaigns with or without memory or retrieval.

The current thesis does not establish every such comparison. Its contribution is to provide the instrumentation and architectural boundaries through which these questions can be investigated systematically.

The contributions can be summarized as follows:

| Research problem | Contribution of the framework |
|---|---|
| LLM flexibility can conflict with operational control | Hybrid agentic–deterministic architecture |
| Static prompt lists do not respond to target behaviour | Closed adaptive campaign loop |
| Generic attacks may ignore application-specific assets | Target dossiers, objectives, and playbooks |
| Prompt count alone is an inadequate progress measure | Category- and objective-level coverage |
| LLM-generated reports may not preserve exact evidence | Deterministic transcript construction and validation |
| AI red-team experiments are difficult to extend consistently | Modular target, provider, and execution abstractions |

## 5.3 Limitations

The framework should be understood as a research prototype rather than a universal vulnerability scanner. Its limitations concern both the implementation itself and the broader difficulty of drawing security conclusions from automated red-team campaigns.

### 5.3.1 Experimental Scope and Generalizability

The empirical conclusions are limited to the targets, models, configurations, and number of repetitions evaluated in this thesis. Intentionally vulnerable applications and capture-the-flag benchmarks provide useful controlled environments, but they do not reproduce the full complexity of production agentic systems. Real deployments may use different model families, orchestration frameworks, authorization architectures, tool protocols, safety layers, and monitoring mechanisms.

Success against a deliberately vulnerable target does not establish effectiveness against hardened systems. Conversely, failure to identify a weakness does not demonstrate that the target is secure. Red-teaming is an open-ended search problem, and no finite campaign can prove the absence of vulnerabilities.

The present evaluation also does not by itself establish superiority over fixed prompt suites, expert human testers, or other automated tools. Such a claim would require repeated trials, common ground truth, comparable test budgets, and statistical analysis across a broader target population. The current work establishes feasibility rather than universal effectiveness.

### 5.3.2 Restricted Attack Surface

The standard workflow primarily performs black-box, text-based testing through a configured chat endpoint. It can observe the input and externally visible response, but it does not comprehensively inspect the target's internal agent graph, retrieved context, memory writes, authorization decisions, tool traces, or intermediate model messages. As a result, it may detect an unsafe outcome without being able to determine its exact internal cause.

The current vulnerability taxonomy concentrates on prompt injection, jailbreaking, information disclosure, and excessive agency. These categories cover important risks but not the complete agentic AI threat landscape. Availability attacks, resource exhaustion, retrieval poisoning, long-term memory poisoning, model and data supply chains, privacy inference, multi-agent trust failures, economic abuse, and complex authorization errors receive limited or indirect coverage.

The transport abstraction is similarly focused on conventional HTTP chat interfaces using text or simple JSON payloads. It does not yet generalize file uploads, images, audio, browser interaction, streaming connections, complex OAuth flows, inter-agent protocols, or standardized model-tool communication interfaces. A persistent HTTP session can preserve cookies, but genuinely stateful multi-turn dialogue is not guaranteed when the target itself is stateless.

### 5.3.3 Dependence on LLM Behaviour and External Services

Attack planning, semantic interpretation, and report generation remain dependent on probabilistic LLM behaviour. Different models may generate different attacks from the same context, and the same model may produce different output across repeated executions. Temperature, provider routing, model updates, context limits, and prompt formatting can all influence the campaign.

The use of externally hosted services also introduces availability, latency, rate-limit, privacy, and cost dependencies. A provider may retire a model or route a generic model identifier to a different implementation. Consequently, deterministic request execution does not make the complete assessment deterministic; it only makes the delivery and recording of the generated tests more reproducible.

Structured task contracts and fallback plans improve resilience, but they can also conceal planning failures. If malformed model output is silently replaced by a generic fallback, the campaign may complete without fully exercising the intended strategy. Such events must therefore remain visible in experimental records.

### 5.3.4 Evidence Classification and Coverage Measurement

The deterministic classifier relies partly on refusal phrases and target-specific lexical markers. These rules provide an operational approximation of the result, not formal ground truth. A sensitive term may appear in a harmless explanation, producing a false positive, while an indirect or paraphrased disclosure may be missed. A response can also contain both a refusal and leaked information, making the correct classification dependent on more than the first matched pattern.

Authorization context further complicates classification. The presence of a record, tool name, or configuration value is only a vulnerability when the requesting identity was not permitted to obtain it. Textual evidence alone may not be sufficient to determine that relationship. Similarly, objective and vulnerability labels inferred from natural language can differ from the metadata originally assigned during planning.

Coverage should therefore not be interpreted as security assurance. Marking an objective as blocked shows that one or more tested payloads were rejected, not that every possible path to that objective is secure. Marking it as vulnerable confirms at least one successful path but does not express severity, exploitability, business impact, or the breadth of affected users. The current state model is useful for campaign guidance, but it remains a coarse abstraction.

The stopping rules are also heuristic. A fixed round budget can terminate before a productive attack path is discovered, while a uniformly blocked batch may reflect inadequate strategy diversity rather than a secure target. Conversely, continued refinement can consume cost without producing meaningful new information.

### 5.3.5 Knowledge Retrieval and Experiential Memory

The active standard workflow is primarily grounded through manually constructed dossiers and playbooks. The retrieval-augmented subsystem is available, but it is not fully integrated into every planning decision. Consequently, the current system adapts more strongly within a campaign than it learns across campaigns.

Experiential memory stores strongly confirmed successful payloads, but its current form is limited. It does not provide mature deduplication, expiry, target-similarity scoring, negative experience, or human approval. New entries do not immediately influence planning; they must later enter the knowledge-ingestion process. Provenance is limited, and techniques successful against one target may not be appropriate for another.

Both retrieved knowledge and experiential memory introduce a further security concern: poisoning. If untrusted content or an incorrectly classified success is stored and later supplied to the Strategist, it may distort future planning. A production system would require trusted-source policies, provenance tracking, sanitization, and review workflows.

### 5.3.6 Target Onboarding and Portability

The target abstraction reduces application-specific coupling, but onboarding remains knowledge-intensive. An operator must define the interface, authentication method, important assets, roles, objectives, evidence markers, and appropriate playbooks. Safe discovery capabilities can assist this process, but the current standard campaign does not provide zero-configuration target understanding.

This manual preparation creates a trade-off. Target-specific knowledge improves relevance and the ability to recognize meaningful evidence, but it can also bias the assessment toward anticipated vulnerabilities. A campaign may become effective at confirming expected weaknesses while overlooking novel ones that are absent from the dossier.

Portability is therefore architectural rather than fully automatic. The framework can support heterogeneous targets through its abstractions, but the amount of expert configuration required has not yet been eliminated.

### 5.3.7 Operational Safety, Scalability, and Evidence Protection

The executor avoids automatically repeating prompts that appear capable of changing state, reducing the chance of duplicate actions after a timeout. This safeguard does not prevent the initial action from being attempted, nor does it provide transaction rollback. Testing a production agent capable of sending messages, moving funds, modifying records, or controlling infrastructure would require stronger policies, isolated test accounts, approval gates, and environmental sandboxing.

Execution is predominantly sequential and state is stored locally. This is appropriate for an experimental prototype, but it limits high-volume campaigns, concurrent assessments, multiple operators, and distributed execution. Shared state can also reduce isolation between runs unless separate campaign storage is configured.

Reports, raw responses, and experiential memory may contain credentials, personal information, or other sensitive evidence. The current prototype does not provide comprehensive automatic redaction, encryption at rest, role-based access control, retention policies, or tamper-evident storage. These controls would be mandatory in many organizational environments.

Scientific reproducibility is also partial. The framework records interactions, but an exact experiment additionally requires the model and provider revision, target build, code revision, dependency versions, configuration snapshot, random parameters, timestamps, and a unique campaign state. Unpinned dependencies and dynamically routed models make exact replication more difficult.

## 5.4 Future Expansion

Future development should address the preceding limitations systematically. The priority should be to strengthen validation and safety before increasing autonomy. Adding more agents without improving ground truth, campaign isolation, and evidence quality would make the system more complex without necessarily making its conclusions more reliable.

### 5.4.1 Broader Evaluation and Reproducibility

The first direction is the construction of a rigorous multi-target evaluation methodology. Future experiments should include intentionally vulnerable and hardened targets from multiple domains, different agent architectures, several LLM families, and targets with distinct tool and memory configurations.

Each configuration should be executed repeatedly. Relevant measurements include attack-success rate, objective coverage, false-positive and false-negative rates, rounds required, execution time, token consumption, monetary cost, and variance between runs. Confidence intervals would make the effect of stochastic planning visible.

Comparative baselines should include static prompt lists, a single-agent configuration, expert human testing where practical, and versions of the framework with feedback, memory, retrieval, or agent specialization disabled. These ablation studies would allow the contribution of each component to be measured rather than inferred from the behaviour of the complete system.

Every campaign should produce a reproducibility manifest containing the exact model identifier, provider route, target version, code revision, taxonomy and playbook versions, configuration, dependency lockfile, timestamps, and campaign identifier. Containerized environments and replayable evidence fixtures would further reduce environmental variation.

### 5.4.2 Broader Attack-Surface and Adapter Coverage

The framework could be extended beyond single-endpoint textual chat. Future adapters could support file and document ingestion, image and audio inputs, browser-controlled agents, streaming APIs, explicit conversation identifiers, external tool protocols, and multi-agent communication channels.

The vulnerability model should expand accordingly. Relevant directions include indirect prompt injection through retrieved documents, RAG poisoning, persistent-memory manipulation, tool-output injection, cross-agent impersonation, confused-deputy behaviour, resource exhaustion, privacy attacks, supply-chain risks, and authorization failures involving multiple services.

A formal plugin interface would allow a target adapter to declare its required authentication, supported input modalities, conversation semantics, available observations, and side-effect risk. Safe capability discovery could generate a draft profile, which an operator would review and approve before execution. This would reduce onboarding effort without allowing the framework to probe unknown systems without authorization.

White-box and grey-box adapters would also improve diagnosis. When instrumentation is available, the framework could correlate the user prompt with retrieved documents, constructed model context, tool selection, authorization decisions, memory changes, and external side effects. This would move the system from detecting an unsafe output toward explaining the causal path that produced it.

### 5.4.3 Improved Adaptive Planning and Result Verification

The current refinement logic can be generalized into an explicit attack-state graph. Nodes could represent hypotheses, prerequisites, discovered facts, and objectives, while edges represent attack steps and evidence dependencies. Such a structure would support genuinely stateful multi-turn campaigns and make it possible to explain how several individually harmless interactions combined into a compromise.

Attack selection could then be guided by coverage, expected information gain, cost, and confidence. Coverage-guided mutation, evolutionary search, multi-armed bandits, or carefully bounded reinforcement learning could be evaluated as alternatives to fixed heuristic refinement. These methods should operate within strict action and budget policies.

Planning could also benefit from additional specialized roles, such as a critic that challenges unsupported assumptions, a mutation agent that generates alternatives, and a judge that compares proposed tests. However, additional agents should only be introduced if controlled experiments show that they improve coverage or efficiency. Multi-agent complexity should not be treated as an objective by itself.

Evidence verification should combine semantic reasoning with stronger deterministic oracles. Synthetic canary records, known authorization boundaries, schema assertions, tool-call traces, and before-and-after state checks can establish whether an action or disclosure actually occurred. Objective identifiers should be propagated unchanged from planning through execution and reporting, rather than inferred again from response text.

A calibrated confidence score could represent the strength of each finding. Conflicts between the LLM Analyzer and deterministic oracles should be recorded explicitly, and ambiguous or high-impact findings should be routed to a human reviewer instead of being forced into a definitive category.

### 5.4.4 Governed Knowledge Retrieval and Long-Term Memory

Retrieval should become an integrated but governed planning service. Every retrieved passage should retain its source, version, date, and trust level. Relevance thresholds and target applicability should determine whether it is included in the Strategist's context. The effect of retrieval should be measured through campaigns with and without it.

Experiential memory should move from an append-only log to a structured store containing successful and unsuccessful techniques, target characteristics, outcome confidence, evidence references, and human validation status. Deduplication, decay, and target-similarity mechanisms would prevent the store from growing indefinitely or transferring irrelevant attacks between domains.

The knowledge pipeline must also defend itself against adversarial content. Retrieved documents and target responses should be treated as untrusted data, separated from control instructions, sanitized where possible, and prevented from modifying the framework's policies. Only validated findings should become reusable experience.

Longer term, privacy-preserving knowledge sharing could allow multiple research groups or organizational teams to exchange generalized attack patterns without exposing target-specific secrets. This would turn individual campaign experience into a curated community resource while retaining governance and provenance.

### 5.4.5 Production-Grade Safety and Governance

A larger system would require a policy engine that evaluates every planned operation before execution. Policies could enforce authorized hosts and endpoints, time windows, prompt and request budgets, permitted tools, maximum cost, data-handling restrictions, and action-risk levels.

Potentially state-changing operations should support dry-run modes, human approval, idempotency keys, isolated test tenants, and rollback procedures. Global circuit breakers and emergency termination controls should stop a campaign when error rates, costs, or unexpected side effects exceed predefined thresholds.

Evidence storage should provide encryption, automatic secret and personal-data redaction, access control, retention schedules, integrity signatures, and an audit log of every view or modification. These measures would allow the framework to be used in environments where discovered vulnerabilities and leaked data are themselves highly sensitive.

Governance must also remain human-centered. Operators should define scope and risk tolerance before execution, and security experts should validate ambiguous findings and assess business impact afterward. Automation should increase testing capacity, not remove accountability.

### 5.4.6 Evolution into a Continuous AI-Security Validation Platform

The framework could ultimately evolve from a local experimental application into a continuous security-validation platform for heterogeneous agentic AI systems. Such a platform could contain:

- a central control plane for scope, policy, campaign scheduling, and operator approval;
- a registry of targets, dossiers, models, playbooks, and execution adapters;
- isolated worker processes for concurrent and distributed campaign execution;
- a versioned knowledge and experiential-memory service;
- encrypted evidence storage and reproducible campaign manifests;
- a review interface for findings, confidence, attack chains, and remediation status;
- an analytics layer for comparing models, releases, defenses, costs, and coverage; and
- integration points for software-delivery and security-monitoring systems.

Confirmed attacks could be converted automatically into regression tests. After a model, prompt, tool, or authorization policy changes, the platform could replay the relevant tests and determine whether the mitigation remains effective. New releases could be evaluated in an isolated environment before deployment, while scheduled campaigns could detect security regressions caused by model updates or changes to retrieved knowledge.

The platform could also support a purple-team workflow. Instead of ending after vulnerability discovery, it could associate a finding with a proposed mitigation, execute the mitigation in a test environment, repeat the relevant attack chain, and preserve evidence of whether the issue was resolved. This would extend the framework from one-time offensive testing to continuous detection, remediation verification, and organizational learning.

A possible development roadmap is summarized below.

| Horizon | Primary objective | Representative developments |
|---|---|---|
| Near term | Improve scientific reliability | Campaign isolation, dependency locking, repeated trials, confidence scoring, stronger test oracles |
| Medium term | Expand technical coverage | Formal adapter interface, stateful attack graphs, multimodal and tool-protocol support, governed RAG |
| Long term | Build a continuous platform | Distributed workers, policy engine, encrypted evidence service, CI/CD integration, remediation verification |

## 5.5 Final Remarks

The results of this thesis support the use of controlled agentic automation as a complementary instrument for AI security assessment. The framework demonstrates that LLM-based planning can participate in a disciplined red-team process when its actions are bounded by deterministic validation, target-aware configuration, explicit feedback, and evidence-preserving reporting.

At the same time, automation does not eliminate the need for expert judgement. Human involvement remains necessary to define the authorized scope, identify valuable assets, evaluate ambiguous evidence, determine business impact, approve consequential actions, and decide whether a mitigation is sufficient. The framework should therefore be understood as an instrument that extends the reach and repeatability of security researchers rather than as a replacement for them.

The broader significance of the work lies in its architectural direction. As agentic AI systems become more capable and more deeply connected to operational environments, security evaluation will need to become continuous, adaptive, and aware of both model behaviour and system-level consequences. The prototype developed in this thesis represents a step toward that goal: a foundation for scalable, evidence-aware, and responsibly governed red-teaming of agentic artificial-intelligence systems.
