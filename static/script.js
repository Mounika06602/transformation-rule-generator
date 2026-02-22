$(document).ready(function() {
    let selectedWorkflowId = null;
    let generatedRules = null;
    
	// Load workflows (backend returns a plain array)
	$.ajax({
		url: '/workflows',
		method: 'GET',
		success: function(response) {
			if (Array.isArray(response)) {
				displayWorkflows(response);
			} else {
				console.error('Invalid response format:', response);
				$('#workflows-container').html('<p class="error">Error: Invalid response format.</p>');
			}
		},
		error: function(error) {
			console.error('Error loading workflows:', error);
			$('#workflows-container').html('<p class="error">Error loading workflows. Please try again.</p>');
		}
	});
    
    // Display workflows
    function displayWorkflows(workflows) {
        if (!workflows || workflows.length === 0) {
            $('#workflows-container').html('<p>No workflows available.</p>');
            return;
        }
        
        let html = '<div class="workflow-cards">';
		for (let i = 0; i < workflows.length; i++) {
			const workflow = workflows[i];
            html += `
				<div class="workflow-card" data-id="${workflow.workflow_id}">
					<h3>${workflow.workflow_name}</h3>
					<p>Status: ${workflow.status || ''}</p>
                </div>
            `;
        }
        html += '</div>';
        
        $('#workflows-container').html(html);
        
        // Add click event to workflow cards
        $('.workflow-card').click(function() {
            $('.workflow-card').removeClass('selected');
            $(this).addClass('selected');
            
            selectedWorkflowId = $(this).data('id');
            loadWorkflowData(selectedWorkflowId);
            
            // Enable generate button
            $('#generate-btn').prop('disabled', false);
        });
    }
    
    // Load workflow data
	function loadWorkflowData(workflowId) {
		$.ajax({
			url: `/workflows/${workflowId}/logs`,
			method: 'GET',
			success: function(data) {
				displayWorkflowData(data);
			},
			error: function(error) {
				console.error('Error loading workflow data:', error);
				$('#workflow-data').html('<p class="error">Error loading workflow data. Please try again.</p>');
			}
		});
	}
    
    // Display workflow data
	function displayWorkflowData(data) {
		// Backend returns an array of log objects: { log_id, log_message, error_type, timestamp }
		let logs = Array.isArray(data) ? data : (data && data.logs ? data.logs : []);
		let logsHtml = '<ul class="logs-list">';
		logs.forEach(function(log) {
			const text = typeof log === 'string' ? log : (log.log_message || JSON.stringify(log));
			let logClass = '';
			const lower = text.toLowerCase();
			if (lower.includes('error')) {
				logClass = 'log-error';
			} else if (lower.includes('warning')) {
				logClass = 'log-warning';
			} else if (lower.includes('info')) {
				logClass = 'log-info';
			}
			logsHtml += `<li class="${logClass}">${text}</li>`;
		});
		logsHtml += '</ul>';
		$('#logs-data').html(logsHtml);
	}
    
    // Generate transformation rules
    $('#generate-btn').click(function() {
        if (!selectedWorkflowId) {
            alert('Please select a workflow first.');
            return;
        }
        
        const userQuery = $('#user-query').val().trim();
        if (!userQuery) {
            alert('Please enter a query.');
            return;
        }
        
        // Show loading indicator
        $('#loading-container').show();
        $('#results-container').hide();
        
		$.ajax({
			url: '/query',
			method: 'POST',
			contentType: 'application/json',
			data: JSON.stringify({
				workflow_id: selectedWorkflowId,
				query_text: userQuery
			}),
            success: function(data) {
                // Hide loading indicator
                $('#loading-container').hide();
                
				// Store generated rules for export
				generatedRules = data.transformation_rules;
                
                // Display results
				if (typeof data.transformation_rules === 'string') {
					$('#rules-content').html('<pre>' + $('<div/>').text(data.transformation_rules).html() + '</pre>');
					$('#results-container').show();
				} else if (Array.isArray(data.transformation_rules)) {
                    // Fallback to manual formatting
                    let rulesHtml = '<div class="rules-grid">';
					data.transformation_rules.forEach(function(rule) {
                            rulesHtml += `
                                <div class="rule-card">
									<h3>${(rule && rule.target_field) || 'Rule'}</h3>
                                <div class="rule-section">
										<strong>Source Fields:</strong> ${Array.isArray(rule && rule.source_fields) ? rule.source_fields.join(', ') : 'N/A'}
                                </div>
                                <div class="rule-section">
										<strong>Transformations:</strong><br> ${Array.isArray(rule && rule.transformations) ? rule.transformations.join('<br>') : 'N/A'}
                                </div>
                                <div class="rule-section">
										<strong>Error Handling:</strong><br> ${Array.isArray(rule && rule.error_handling) ? rule.error_handling.join('<br>') : 'N/A'}
                                </div>
                                <div class="rule-section">
										<strong>Validation:</strong><br> ${Array.isArray(rule && rule.validation) ? rule.validation.join('<br>') : 'N/A'}
                                </div>
                            </div>
                        `;
                    });
                    rulesHtml += '</div>';
                    $('#rules-content').html(rulesHtml);
                }
                
                // Display error reasoning
				if (data.error_reasoning) {
					$('#error-reasoning').html(data.error_reasoning);
                } else {
                    // Fallback to simple error display
                    let errorHtml = '<div class="error-reasoning">';
                    errorHtml += '<h3>Log Analysis</h3>';
                    
					if (data.error_analysis) {
						// Show the analysis as JSON for clarity
						errorHtml += '<pre>' + $('<div/>').text(JSON.stringify(data.error_analysis, null, 2)).html() + '</pre>';
					} else {
						errorHtml += '<p>No detailed log analysis available.</p>';
					}
                    
                    errorHtml += '</div>';
                    $('#error-reasoning').html(errorHtml);
                }
                
                $('#results-container').show();
            },
            error: function(xhr, status, error) {
                // Hide loading indicator
                $('#loading-container').hide();
                
                console.error('Error generating rules:', xhr, status, error);
                
                // Display error in the UI instead of alert
                $('#results-container').show();
                $('#rules-content').html('<div class="error-message"><h3>Error</h3><p>Failed to generate transformation rules. Please try again.</p></div>');
                $('#error-reasoning').html('<div class="error-details"><p>Server error occurred. This could be due to an invalid API key or server issue.</p></div>');
            }
        });
    });
    
    // Export to Excel
    $('#export-btn').click(function() {
        if (!generatedRules || !selectedWorkflowId) {
            alert('No transformation rules to export.');
            return;
        }
        
        $.ajax({
            url: '/api/export-excel',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                workflow_id: selectedWorkflowId,
                transformation_rules: generatedRules
            }),
            success: function(data) {
                if (data.filename) {
                    // Download the file
                    window.location.href = `/download/${data.filename}`;
                } else {
                    alert('Error exporting to Excel.');
                }
            },
            error: function(error) {
                console.error('Error exporting to Excel:', error);
                alert('Error exporting to Excel. Please try again.');
            }
        });
    });
});