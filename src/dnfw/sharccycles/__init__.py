"""A cycle estimate for SHARC+ code from an instruction-level run.

digikit's runner counts instructions; the ADSP-21569 spends cycles. This package
turns a run's step stream into counts of the events the SHARC+ Programming
Reference prices (stalls, flushes, memory waits), and prices them with a cost
table that the instrument's load readings tune.

Modules, one subject each:

  regions      an address -> the memory it lands in (datasheet Tables 2-6)
  computefield a compute field -> its unit, float-ness, destinations, sources
  forms        a decoded instruction -> its static facts (DAG use, branch kind)
  cache        a set-associative LRU cache, counting hits and misses
  btb          the branch target buffer: 2 ways x 128 sets, 2-bit counters
  events       the per-step record the model consumes
  model        the step stream -> event counts (the stall rules)
  costs        the cost table, its sources, and the estimate
  fit          non-negative least squares over measured cases

Nothing here imports digikit: the adapter that turns a runner's steps into
`events.Step` lives in scripts/sharc_cycles_recorder.py.
"""
