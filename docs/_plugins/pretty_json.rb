# `{{ record | pretty_json }}` — like Jekyll's built-in `jsonify`, but indented
# so the raw-data block on an app page is readable instead of one long line.
require "json"

module ElectronSurvey
  module PrettyJsonFilter
    def pretty_json(input)
      JSON.pretty_generate(input)
    end
  end
end

Liquid::Template.register_filter(ElectronSurvey::PrettyJsonFilter)
