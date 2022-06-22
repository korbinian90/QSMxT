#!/usr/bin/env julia
using MriResearchTools
import Pkg

error(ENV["JULIA_BINDIR"])

in_path = ARGS[1]
out_path = ARGS[2]

phase_nii = niread(in_path)
phase = Float32.(phase_nii)
laplacianunwrap!(phase)
savenii(phase, out_path; header=header(phase_nii))
