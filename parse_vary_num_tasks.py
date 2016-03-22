"""
This file copies bacsk the most recent 5 job log bundles from the given
master and generates a graph plotting the job completion time as a function
of the number of tasks used.
"""

import numpy
import os
import re
import subprocess
import sys

import parse_event_logs
import utils

def filter(all_jobs_dict):
  sorted_jobs = sorted(all_jobs_dict.iteritems())
   # Eliminate the first two jobs (the first one is a warmup job,
   # and the second job was responsible for generating the input RDD and caching
   # it in-memory), and then every other job (since every other job just does GC).
  filtered_jobs = sorted_jobs[3::2]
  return {k:v for (k,v) in filtered_jobs}

def copy_data(driver_hostname, identity_file, output_prefix, num_experiments, username):
  list_filenames_command = "ls -t /mnt/experiment_log_*gz | head -n " + num_experiments
  event_log_filenames = utils.ssh_get_stdout(
    driver_hostname,
    identity_file,
    username,
    list_filenames_command).strip("\n").strip("\r")
  print event_log_filenames

  for event_log_filename in event_log_filenames.split("\n"):
    event_log_filename = event_log_filename.strip("\r")
    basename = os.path.basename(event_log_filename)
    local_zipped_logs_name = os.path.join(output_prefix, basename)
    print ("Copying event log from file %s back to %s" %
      (event_log_filename, local_zipped_logs_name))
    utils.scp_from(
      driver_hostname,
      identity_file,
      username,
      event_log_filename,
      local_zipped_logs_name)

    # Unzip the file.
    subprocess.check_call(
      "tar -xvzf %s -C %s" % (local_zipped_logs_name, output_prefix),
      shell=True)

    local_filenames.append(os.path.join(local_zipped_logs_name[:-7], "event_log"))

def main(argv):
  if len(argv) < 2:
    print ("Usage: parse_vary_num_tasks.py output_directory [opt (to copy data): driver_hostname " +
        "identity_file num_experiments]")
    sys.exit(1)

  output_prefix = argv[1]
  if (not os.path.exists(output_prefix)):
    os.mkdir(output_prefix)

  if len(argv) >= 5:
    driver_hostname = argv[2]
    identity_file = argv[3]
    num_experiments = argv[4]
    copy_data(driver_hostname, identity_file, output_prefix, num_experiments, "root")

  all_dirnames = [d for d in os.listdir(output_prefix) if "experiment" in d and "tar.gz" not in d]
  all_dirnames.sort(key = lambda d: int(re.search('experiment_log_([0-9]*)_', d).group(1)))

  output_filename = os.path.join(output_prefix, "actual_runtimes")
  output_file = open(output_filename, "w")

  for dirname in all_dirnames:
    local_event_log_filename = os.path.join(output_prefix, dirname, "event_log")
    print "Parsing event log in %s" % local_event_log_filename
    analyzer = parse_event_logs.Analyzer(local_event_log_filename, job_filterer = filter)

    all_jobs = analyzer.jobs.values()
    num_tasks_values = [len(stage.tasks) for job in all_jobs
      for (stage_id, stage) in job.stages.iteritems()]
    # Assumes all of the map and reduce staages use the same number of tasks.
    num_tasks = num_tasks_values[0]

    ideal_runtimes_millis = []
    ideal_runtimes_utilization_millis = []
    ideal_map_runtimes_millis = []
    actual_map_runtimes_millis = []
    ideal_reduce_runtimes_millis = []
    actual_reduce_runtimes_millis = []

    for job in all_jobs:
      job_ideal_millis = 0
      job_ideal_utilization_millis = 0
      for (stage_id, stage) in job.stages.iteritems():
        job_ideal_millis += stage.ideal_time(cores_per_machine = 8, disks_per_machine = 0)
        stage_ideal_utilization_millis = stage.ideal_time_utilization(8)
        job_ideal_utilization_millis += stage_ideal_utilization_millis
        if stage.has_shuffle_read():
          ideal_reduce_runtimes_millis.append(stage_ideal_utilization_millis)
          actual_reduce_runtimes_millis.append(stage.runtime())
        else:
          ideal_map_runtimes_millis.append(stage_ideal_utilization_millis)
          actual_map_runtimes_millis.append(stage.runtime())
      ideal_runtimes_millis.append(job_ideal_millis)
      ideal_runtimes_utilization_millis.append(job_ideal_utilization_millis)

    print "Ideal times based on util:", ideal_runtimes_utilization_millis
    print "Ideal runtimes:", ideal_runtimes_millis
    print "Ideal map runtimes:", ideal_map_runtimes_millis
    print "Ideal reduce runtimes:", ideal_reduce_runtimes_millis

    actual_runtimes_millis = [job.runtime() for job in all_jobs]
    actual_over_ideal = [actual / ideal
      for actual, ideal in zip(actual_runtimes_millis, ideal_runtimes_utilization_millis)]

    print "Actual runtimes:", actual_runtimes_millis
    data_to_write = [
      num_tasks,
      min(actual_runtimes_millis),
      numpy.percentile(actual_runtimes_millis, 50), # 3
      max(actual_runtimes_millis),
      min(ideal_runtimes_millis),
      numpy.percentile(ideal_runtimes_millis, 50), # 6
      max(ideal_runtimes_millis),
      min(actual_over_ideal),
      numpy.percentile(actual_over_ideal, 50), # 9
      max(actual_over_ideal),
      min(ideal_runtimes_utilization_millis),
      numpy.percentile(ideal_runtimes_utilization_millis, 50), # 12
      max(ideal_runtimes_utilization_millis),
      min(actual_map_runtimes_millis),
      numpy.percentile(actual_map_runtimes_millis, 50), # 15
      max(actual_map_runtimes_millis),
      min(ideal_map_runtimes_millis),
      numpy.percentile(ideal_map_runtimes_millis, 50), # 18
      max(ideal_map_runtimes_millis),
      min(actual_reduce_runtimes_millis),
      numpy.percentile(actual_reduce_runtimes_millis, 50), # 21
      max(actual_reduce_runtimes_millis),
      min(ideal_reduce_runtimes_millis),
      numpy.percentile(ideal_reduce_runtimes_millis, 50), # 24
      max(ideal_reduce_runtimes_millis)]
    output_file.write("\t".join([str(x) for x in data_to_write]))
    output_file.write("\n")
  output_file.close()

  plot(output_prefix, "actual_runtimes", "actual_runtimes.gp", "plot_vary_num_tasks_base.gp")
  plot(output_prefix, "actual_runtimes", "actual_runtimes_map_reduce.gp", "plot_vary_num_tasks_map_reduce_base.gp")

def plot(output_prefix, data_filename, plot_filename, plot_base):
  absolute_plot_filename = os.path.join(output_prefix, plot_filename)
  data_filename = os.path.join(output_prefix, data_filename)
  plot_file = open(absolute_plot_filename, "w")
  for line in open(plot_base, "r"):
    new_line = line.replace("__NAME__", data_filename)
    plot_file.write(new_line)
  plot_file.close()

  subprocess.check_call("gnuplot %s" % absolute_plot_filename, shell=True)
  output_filename = absolute_plot_filename[:-3]
  subprocess.check_call("open %s.pdf" % output_filename, shell=True)

if __name__ == "__main__":
  main(sys.argv)
