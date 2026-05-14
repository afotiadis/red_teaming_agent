# Implementation Roadmap: Logic Fixes vs. RAG Enrichment

## Timeline & Dependencies

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           YOUR CURRENT STATE                                │
│                                                                             │
│  Level 1: ✓ 100% (direct clue leak)                                       │
│  Level 2: ✓ ~80% (definition extraction works)                            │
│  Level 3: ✗ 0% (definition → guess broken, no RAG help)                   │
│  Level 4+: Not reached                                                      │
│  Overall: 66% success                                                       │
│                                                                             │
│  RAG Status: Exists but sparse, underutilized for guesses                  │
└─────────────────────────────────────────────────────────────────────────────┘

                                    ↓

┌──────────────────────────────────────────────────────────────────────────────┐
│                 PHASE 1: CORE LOGIC FIXES (6-8 hours)                       │
│                                                                              │
│  Fix #1: Definition → Guess Generation                                      │
│    Input: "transmission of energy through space"                           │
│    Output: [wave, signal, light, radiation, transmission]                  │
│    Method: Hardcoded semantic clusters (no RAG needed)                     │
│                                                                              │
│  Fix #2: Advanced Prompt Escalation                                         │
│    New families: constraint_synthesis, semantic_narrowing, meta_reasoning  │
│    Rounds: Extend from 7 to 10-12 for Level 3+                            │
│                                                                              │
│  Fix #3: Clue Memory Escalation                                             │
│    Synthesis: "You said A, B, C → Must be X"                              │
│    Method: Build on accumulated clues, not restart                         │
│                                                                              │
│  EXPECTED RESULT:                                                            │
│    Level 1: ✓ 100% (faster, 3-4 rounds)                                   │
│    Level 2: ✓ 100% (6-7 rounds)                                           │
│    Level 3: ✓ 50% (9-12 rounds) ← MAJOR IMPROVEMENT!                     │
│    Level 4: ~ 30% (new defenses)                                           │
│    Overall: ~82% average                                                    │
│                                                                              │
│  RAG USED: No (just hardcoded clusters in code)                            │
│  Thesis Ready: Yes ✓                                                        │
└──────────────────────────────────────────────────────────────────────────────┘

                                    ↓

           (Checkpoint: Test, validate results, write to thesis)

                                    ↓

┌──────────────────────────────────────────────────────────────────────────────┐
│           PHASE 2: RAG ENRICHMENT (4-6 hours) - OPTIONAL                    │
│                                                                              │
│  Step 1: Document Gandalf Patterns                                          │
│    Create: skills/gandalf-ctf/PATTERNS.md                                  │
│    Content: Level strategies, semantic clusters, clue patterns             │
│                                                                              │
│  Step 2: Add Semantic Clusters                                              │
│    Create: data/gandalf_semantic_clusters.json                             │
│    Content: transmission→wave, growth→potential, etc.                      │
│                                                                              │
│  Step 3: Ingest into RAG                                                    │
│    Method: Update ingest_knowledge.py to load Gandalf docs                │
│    Verify: Chroma DB has Gandalf-specific docs                            │
│                                                                              │
│  Step 4: Wire RAG to Guess Generation                                       │
│    Modify: _build_guess_candidates_from_clues()                            │
│    Add: RAG lookup for semantic enrichment                                 │
│                                                                              │
│  EXPECTED RESULT:                                                            │
│    Level 3: ✓ 50% → 60-65% (RAG provides semantic hints)                 │
│    Level 4: ✓ 30% → 40-45% (Gandalf patterns help)                       │
│    Overall: ~82% → ~85%                                                     │
│                                                                              │
│  RAG USED: Yes (semantic clusters + Gandalf patterns)                      │
│  Thesis Value: Medium (nice-to-have optimization)                           │
│  Implementation Complexity: Low (modular, testable)                         │
└──────────────────────────────────────────────────────────────────────────────┘

                                    ↓

           (Final thesis submission with enhanced RAG support)
```

---

## Risk/Effort Matrix

### Phase 1 (Core Fixes)
```
Effort: ████░░░░░░ (6-8 hours)
Risk:   ██░░░░░░░░ (Low - surgical changes)
Impact: ████████░░ (High - 0% → 50% Level 3)
Value:  ████████░░ (Essential for thesis)
```

**Key Risks (Low):**
- May need to tweak semantic clusters for your specific Gandalf version
- Prompt families might need tuning per level

**Mitigation:**
- Test each fix independently
- Keep original gandalf_game.py as backup
- Use git branches for each fix

---

### Phase 2 (RAG Enrichment)
```
Effort: ███░░░░░░░ (4-6 hours)
Risk:   ░░░░░░░░░░ (Very Low - additive, no breaking changes)
Impact: █░░░░░░░░░ (Low - 3-5% additional improvement)
Value:  ███░░░░░░░ (Nice-to-have for robustness)
```

**Key Risks (None):**
- Purely additive, doesn't break Phase 1 code
- Can test separately from Phase 1
- Can defer to after thesis submission

**Benefits:**
- Future runs benefit from Gandalf knowledge base
- Validates RAG architecture for your thesis
- Demonstrates multi-phase development

---

## Decision Matrix

| Decision | Phase 1 Only | Both Phases |
|----------|-------------|------------|
| **Time to Level 3 success** | 1-2 days | 2-3 days |
| **Thesis completion** | ✓ Ready | ✓ Enhanced |
| **RAG utilization** | No | Yes |
| **Level 3 clearance target** | 50% | 60-65% |
| **Code cleanup** | Partial | Full |
| **Risk** | Low | Very Low |
| **Recommended for deadline** | YES | If time permits |

---

## Code Changes Summary

### Phase 1: Core Logic (gandalf_game.py)

**Add ~150 lines:**
```
+ _generate_guesses_from_definition() [40 lines]
+ semantic_clusters dict [30 lines]
+ constraint_synthesis prompts [20 lines]
+ semantic_narrowing prompts [20 lines]
+ meta_reasoning prompts [20 lines]
Modify: _build_guess_candidates_from_clues() [+30 lines]
Modify: ATTACK_STRATEGY_BANK [+20 lines]
Modify: max_rounds logic [5 lines]
```

**Total changes: ~185 lines**
**Complexity: Medium (logic + data)**
**Test coverage needed: Definition parsing, prompt generation**

---

### Phase 2: RAG Integration

**Create (~200 lines):**
```
+ skills/gandalf-ctf/PATTERNS.md [150 lines]
+ data/gandalf_semantic_clusters.json [50 lines]
```

**Modify (~50 lines):**
```
Modify: ingest_knowledge.py [+20 lines]
Modify: _build_guess_candidates_from_clues() [+30 lines]
```

**Total changes: ~250 lines (mostly documentation)**
**Complexity: Low (mostly config/data)**
**Test coverage needed: RAG queries, semantic cluster loading**

---

## Validation Checkpoints

### After Phase 1
```
✓ Definition parsing extracts semantic candidates
✓ Level 3 clears at least 40% of runs
✓ Level 1-2 regression tests pass
✓ Prompt families logged for analysis
```

### After Phase 2
```
✓ RAG queries return Gandalf-specific docs
✓ Semantic clusters load correctly
✓ Level 3-4 clearance improves by 5-10%
✓ No regression from Phase 1
```

---

## My Recommendation

### For Thesis Deadline (Next 1-2 weeks)
**Implement Phase 1 Only:**
- Cleaner, faster to implement
- Solves the core Level 3 problem
- Hardcoded clusters are simple and reliable
- RAG can be Phase 2 after thesis

### For Long-term Project (After Deadline)
**Then add Phase 2:**
- Enriches RAG with Gandalf knowledge
- Demonstrates multi-phase architecture
- Sets foundation for future red-teaming campaigns
- Shows you understand knowledge engineering

### If You Have Extra Time (Rare)
**Do Both:**
- Implement Phase 1 first (get baseline working)
- Then Phase 2 while testing Phase 1
- Have everything ready for demo/submission

---

## Quick Start Checklist

### To Start Phase 1
- [ ] Back up gandalf_game.py (git branch)
- [ ] Read GANDALF_ANALYSIS_AND_FIXES.md in detail
- [ ] Implement Fix #1: `_generate_guesses_from_definition()`
- [ ] Test on Level 3 with definition clues
- [ ] Implement Fix #2: Add advanced prompt families
- [ ] Test on Level 3 with escalation
- [ ] Implement Fix #3: Clue memory synthesis
- [ ] Run full test suite (Levels 1-3)
- [ ] Measure success rate improvement

### To Start Phase 2 (If doing it)
- [ ] Create skills/gandalf-ctf/PATTERNS.md
- [ ] Create data/gandalf_semantic_clusters.json
- [ ] Modify ingest_knowledge.py
- [ ] Run ingest to load into Chroma
- [ ] Modify _build_guess_candidates_from_clues()
- [ ] Test RAG-backed guess generation
- [ ] Measure improvement from Phase 1

---

## Next Step

**What would you like to do?**

1. **Proceed with Phase 1 only** (recommended)
   - Start implementing Core Fixes immediately
   - Faster path to Level 3 success

2. **Plan both phases** (if time permits)
   - I can create detailed spec for Phase 2 upfront
   - Run both in parallel/sequence

3. **Understand RAG better first** (if uncertain)
   - Dive deeper into RAG enrichment patterns
   - See examples of effective knowledge base design

4. **Something else?**
   - Ask clarifying questions
   - Adjust timeline/scope

Let me know and I'll proceed with the next step!
