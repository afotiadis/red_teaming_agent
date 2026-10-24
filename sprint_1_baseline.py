#!/usr/bin/env python3
"""
Sprint 1 Baseline Evaluation Runner

This script runs the Gandalf game 5 times and collects detailed metrics
to establish the baseline performance before architectural improvements.

Usage:
    python sprint_1_baseline.py [num_runs] [max_levels]

Examples:
    python sprint_1_baseline.py 5 3     # Run 5 times, test levels 1-3
    python sprint_1_baseline.py 3 8     # Run 3 times, test all 8 levels
"""

import os
import sys
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.gandalf_metrics import (
    GandalfMetricsTracker, evaluate_game_run, format_metrics_report, 
    save_metrics_json, _get_gandalf_real_passwords
)


def run_gandalf_game(run_number: int, max_levels: int = 3) -> tuple[str, bool]:
    """
    Run a single Gandalf game session.
    
    Returns:
        (results_filename, success) tuple
    """
    agent_name = f"baseline_run_{run_number:02d}"
    
    print(f"\n{'='*100}")
    print(f"RUN {run_number}: {agent_name}")
    print(f"{'='*100}\n")
    
    try:
        result = subprocess.run(
            [sys.executable, "gandalf_game.py", agent_name, str(max_levels)],
            cwd=PROJECT_ROOT,
            capture_output=False,
            timeout=600,  # 10 minutes per run
        )
        
        # Check if results file was created
        results_file = os.path.join(PROJECT_ROOT, f"gandalf_results_{agent_name}.json")
        if os.path.exists(results_file):
            return results_file, result.returncode == 0
        else:
            print(f"⚠ Warning: Results file not found for {agent_name}")
            return None, False
            
    except subprocess.TimeoutExpired:
        print(f"⚠ Warning: Run {run_number} timed out after 10 minutes")
        return None, False
    except Exception as e:
        print(f"✗ Error running game: {e}")
        return None, False


def aggregate_metrics(results_files: list[str]) -> dict:
    """
    Aggregate metrics across multiple game runs.
    
    Returns:
        Dict with aggregated metrics by level
    """
    aggregated = {}
    real_passwords = _get_gandalf_real_passwords()
    
    for results_file in results_files:
        if not results_file or not os.path.exists(results_file):
            continue
        
        try:
            metrics_by_level = evaluate_game_run(results_file, real_passwords)
            
            for level_num, metrics in metrics_by_level.items():
                if level_num not in aggregated:
                    aggregated[level_num] = {
                        "clears": [],
                        "clue_densities": [],
                        "false_positive_rates": [],
                        "semantic_coverages": [],
                        "guess_accuracies": [],
                        "confidence_calibrations": [],
                    }
                
                aggregated[level_num]["clears"].append(metrics.runs_cleared)
                aggregated[level_num]["clue_densities"].append(metrics.total_clue_density)
                aggregated[level_num]["false_positive_rates"].append(metrics.total_false_positive_rate)
                aggregated[level_num]["semantic_coverages"].append(metrics.total_semantic_coverage)
                aggregated[level_num]["guess_accuracies"].append(metrics.total_guess_accuracy)
                aggregated[level_num]["confidence_calibrations"].append(metrics.total_confidence_calibration)
        
        except Exception as e:
            print(f"⚠ Error processing {results_file}: {e}")
    
    return aggregated


def compute_aggregate_stats(aggregated: dict) -> dict:
    """Compute mean and std dev for aggregated metrics."""
    stats = {}
    
    for level_num, data in aggregated.items():
        stats[level_num] = {
            "clear_rate": sum(data["clears"]) / len(data["clears"]) if data["clears"] else 0,
            "avg_clue_density": sum(data["clue_densities"]) / len(data["clue_densities"]) if data["clue_densities"] else 0,
            "avg_fp_rate": sum(data["false_positive_rates"]) / len(data["false_positive_rates"]) if data["false_positive_rates"] else 0,
            "avg_semantic_coverage": sum(data["semantic_coverages"]) / len(data["semantic_coverages"]) if data["semantic_coverages"] else 0,
            "avg_guess_accuracy": sum(data["guess_accuracies"]) / len(data["guess_accuracies"]) if data["guess_accuracies"] else 0,
            "num_runs": len(data["clears"]),
        }
    
    return stats


def print_aggregate_report(stats: dict):
    """Print aggregated metrics across all runs."""
    print("\n" + "="*100)
    print("SPRINT 1 BASELINE SUMMARY (Aggregated Across All Runs)")
    print("="*100 + "\n")
    
    print(f"{'Level':<8} {'Clear%':<12} {'Clues/Resp':<15} {'FP Rate':<12} {'Sem. Cov.':<12} {'Guess Acc.':<12} {'Runs':<6}")
    print("-" * 100)
    
    for level_num in sorted(stats.keys()):
        s = stats[level_num]
        clear_pct = s["clear_rate"] * 100
        clue_density = s["avg_clue_density"]
        fp_rate = s["avg_fp_rate"]
        sem_cov = s["avg_semantic_coverage"]
        guess_acc = s["avg_guess_accuracy"]
        num_runs = s["num_runs"]
        
        print(
            f"{level_num:<8} {clear_pct:<12.1f} {clue_density:<15.2f} {fp_rate:<12.1%} "
            f"{sem_cov:<12.1%} {guess_acc:<12.1%} {num_runs:<6}"
        )
    
    print("\n" + "="*100)


def main():
    """Main baseline evaluation runner."""
    num_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    max_levels = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    
    print(f"\n{'='*100}")
    print("SPRINT 1: BASELINE METRICS COLLECTION")
    print(f"Running {num_runs} complete Gandalf game cycles (levels 1-{max_levels})")
    print(f"{'='*100}\n")
    
    start_time = time.time()
    results_files = []
    
    # Run multiple games
    for run_num in range(1, num_runs + 1):
        results_file, success = run_gandalf_game(run_num, max_levels)
        if results_file:
            results_files.append(results_file)
            print(f"✓ Run {run_num} completed")
        else:
            print(f"✗ Run {run_num} failed")
        
        # Brief pause between runs
        if run_num < num_runs:
            time.sleep(2)
    
    # Aggregate metrics
    print(f"\n{'='*100}")
    print("AGGREGATING METRICS ACROSS ALL RUNS")
    print(f"{'='*100}\n")
    
    aggregated = aggregate_metrics(results_files)
    stats = compute_aggregate_stats(aggregated)
    
    # Print aggregate report
    print_aggregate_report(stats)
    
    # Save aggregate report
    aggregate_file = os.path.join(PROJECT_ROOT, f"gandalf_baseline_report.json")
    with open(aggregate_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "num_runs": num_runs,
            "max_levels": max_levels,
            "results_files": results_files,
            "aggregate_stats": {
                str(k): {
                    "clear_rate": v["clear_rate"],
                    "avg_clue_density": v["avg_clue_density"],
                    "avg_fp_rate": v["avg_fp_rate"],
                    "avg_semantic_coverage": v["avg_semantic_coverage"],
                    "avg_guess_accuracy": v["avg_guess_accuracy"],
                    "num_runs": v["num_runs"],
                }
                for k, v in stats.items()
            }
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Aggregate report saved to: {aggregate_file}")
    
    elapsed = time.time() - start_time
    print(f"\nTotal time: {elapsed/60:.1f} minutes")
    print(f"\n{'='*100}\n")


if __name__ == "__main__":
    main()
