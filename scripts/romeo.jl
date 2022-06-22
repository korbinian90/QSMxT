#!/usr/bin/env julia
using MriResearchTools
using ArgParse

s = ArgParseSettings()
@add_arg_table! s begin
    "--phase"
        help = "input - phase filename"
        required = true
    "--mag"
        help = "input - mag filename"
        required = false
    "--echo-times", "-t"
        help = "input - echo times"
        required = true
        nargs = '+'
    "--output"
        help = "output - unwrapped phase filename"
        required = true
end

function getTEs(settings)
    TEs = eval(Meta.parse(join(settings["echo-times"], " ")))
    if TEs isa AbstractMatrix
        TEs = TEs[:]
    end
    return TEs
end

args = parse_args(ARGS, s)

phase_nii = niread(args["phase"])
phase = Float32.(phase_nii)
TEs = getTEs(args)
unwrapped = romeo(phase; TEs)
savenii(unwrapped, args["output"]; header=header(phase_nii))
